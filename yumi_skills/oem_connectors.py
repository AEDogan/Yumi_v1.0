"""Provider-neutral contracts and OAuth PKCE primitives for OEM linking.

Each manufacturer still needs its own registered Yumi app and adapter. This
module owns the common authorization safety rules and normalized device shape;
it does not pretend that every OEM exposes one universal API.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    name: str
    account_linking: str
    device_types: tuple[str, ...]
    capabilities: tuple[str, ...]
    supported_models: str
    commands: dict[str, tuple[str, ...]] = field(default_factory=dict)
    enabled: bool = False


@dataclass(frozen=True)
class DeviceDescriptor:
    provider_id: str
    account_id: str
    device_id: str
    name: str
    device_type: str
    capabilities: tuple[str, ...]
    model: str = ""
    room: str = ""


class OEMConnector(Protocol):
    """One OEM adapter, implemented against that OEM's official API/SDK."""

    spec: ProviderSpec

    def begin_link(self) -> dict[str, Any]: ...

    def finish_link(self, callback: dict[str, Any]) -> dict[str, Any]: ...

    def discover(self, account: dict[str, Any]) -> list[DeviceDescriptor]: ...

    def execute(
        self, account: dict[str, Any], device: DeviceDescriptor,
        capability: str, command: str, value: Any = None,
    ) -> dict[str, Any]: ...

    def unlink(self, account: dict[str, Any]) -> None: ...


class ConnectorRegistry:
    """Explicit provider registry; never advertises an unimplemented OEM."""

    def __init__(self) -> None:
        self._connectors: dict[str, OEMConnector] = {}

    def register(self, connector: OEMConnector) -> None:
        provider_id = connector.spec.id.strip().casefold()
        if not provider_id or provider_id in self._connectors:
            raise ValueError("OEM connector id is empty or already registered")
        if not connector.spec.enabled:
            raise ValueError("A disabled OEM connector cannot be registered")
        self._connectors[provider_id] = connector

    def get(self, provider_id: str) -> OEMConnector:
        try:
            return self._connectors[provider_id.strip().casefold()]
        except KeyError:
            raise LookupError("This OEM account connector is not configured in Yumi") from None

    def specs(self) -> tuple[ProviderSpec, ...]:
        return tuple(connector.spec for connector in self._connectors.values())

    def has(self, provider_id: str) -> bool:
        return provider_id.strip().casefold() in self._connectors


@dataclass(frozen=True)
class OAuthPKCEConfig:
    authorization_url: str
    token_url: str
    client_id: str
    scopes: tuple[str, ...] = ()
    authorize_params: dict[str, str] = field(default_factory=dict)
    token_params: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for value in (self.authorization_url, self.token_url):
            parsed = urllib.parse.urlsplit(value)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("OEM OAuth endpoints must be credential-free HTTPS URLs")
        if not self.client_id.strip():
            raise ValueError("Yumi's OEM application client id is not configured")


class LoopbackOAuthPKCE:
    """Short-lived loopback callback for public OEM clients that support PKCE.

    Confidential-client OEM APIs must exchange codes in a Yumi-owned backend;
    this desktop helper deliberately has no client-secret parameter.
    """

    def __init__(self, config: OAuthPKCEConfig) -> None:
        self.config = config
        self._state = secrets.token_urlsafe(32)
        self._verifier = secrets.token_urlsafe(48)
        digest = hashlib.sha256(self._verifier.encode("ascii")).digest()
        self._challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        self._event = threading.Event()
        self._code: str | None = None
        self._error: str | None = None
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._redirect_uri: str | None = None

    @property
    def redirect_uri(self) -> str:
        if self._redirect_uri is None:
            self._ensure_server()
        assert self._redirect_uri is not None
        return self._redirect_uri

    def authorization_url(self) -> str:
        redirect = self.redirect_uri
        params = {
            **self.config.authorize_params,
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": redirect,
            "state": self._state,
            "code_challenge": self._challenge,
            "code_challenge_method": "S256",
        }
        if self.config.scopes:
            params["scope"] = " ".join(self.config.scopes)
        parts = urllib.parse.urlsplit(self.config.authorization_url)
        query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        query.extend(params.items())
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path,
                                        urllib.parse.urlencode(query), ""))

    def wait_for_code(self, timeout: float = 300.0) -> str:
        self._ensure_server()
        try:
            if not self._event.wait(max(0.0, min(float(timeout), 600.0))):
                raise TimeoutError("OEM account linking timed out")
            if self._error:
                raise RuntimeError("OEM authorization was not completed")
            if not self._code:
                raise RuntimeError("OEM authorization returned no code")
            return self._code
        finally:
            self.close()

    def exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange a validated callback code using PKCE and a public client."""
        payload = {
            **self.config.token_params,
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self.config.client_id,
            "redirect_uri": self.redirect_uri,
            "code_verifier": self._verifier,
        }
        request = urllib.request.Request(
            self.config.token_url,
            data=urllib.parse.urlencode(payload).encode("ascii"),
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            opener = urllib.request.build_opener(_SameOriginHTTPSRedirect())
            with opener.open(request, timeout=15) as response:
                result = json.loads(response.read(1_000_000).decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError, UnicodeError) as error:
            raise RuntimeError("OEM token exchange failed") from error
        if not isinstance(result, dict) or not isinstance(result.get("access_token"), str):
            raise RuntimeError("OEM token response did not contain an access token")
        return result

    def _ensure_server(self) -> None:
        if self._server is not None:
            return
        if self._redirect_uri is not None:
            raise RuntimeError("OEM authorization callback has already expired")
        owner = self

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib handler interface
                parsed = urllib.parse.urlsplit(self.path)
                query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
                state = query.get("state", [""])[0]
                code = query.get("code", [""])[0]
                error = query.get("error", [""])[0]
                valid_path = parsed.path == "/oauth/callback"
                if not valid_path or not secrets.compare_digest(state, owner._state):
                    status, message = 400, "Authorization response could not be verified."
                elif error:
                    owner._error = "provider_denied"
                    status, message = 200, "OEM account linking was cancelled. You can close this tab."
                elif not code or len(code) > 4096:
                    status, message = 400, "The OEM did not return an authorization code."
                else:
                    owner._code = code
                    status, message = 200, "Yumi account link received. You can close this tab."
                if status == 200:
                    owner._event.set()
                body = message.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *args: Any) -> None:
                return  # OAuth codes and state never enter logs.

        self._server = HTTPServer(("127.0.0.1", 0), CallbackHandler)
        self._server.timeout = 0.5
        self._redirect_uri = f"http://127.0.0.1:{self._server.server_port}/oauth/callback"

        def serve_once() -> None:
            assert self._server is not None
            deadline = time.monotonic() + 600
            while not self._event.is_set() and time.monotonic() < deadline:
                self._server.handle_request()

        self._thread = threading.Thread(target=serve_once, name="YumiOEMOAuthCallback", daemon=True)
        self._thread.start()

    def close(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.server_close()


class _SameOriginHTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        old = urllib.parse.urlsplit(request.full_url)
        new = urllib.parse.urlsplit(new_url)
        if (old.scheme, old.hostname, old.port) != ("https", new.hostname, new.port) or new.scheme != "https":
            raise urllib.error.HTTPError(new_url, code, "Cross-origin OEM token redirect refused", headers, fp)
        return super().redirect_request(request, fp, code, message, headers, new_url)

