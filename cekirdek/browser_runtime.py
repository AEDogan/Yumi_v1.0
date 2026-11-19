"""Normal Chromium on a private Windows desktop; never switch the user's desktop.

The browser keeps its ordinary rendering/login environment without putting a
window or taskbar button on the interactive desktop. Explicit sign-in uses the
interactive desktop instead. No credentials, cookies or verification are altered.
"""
import ctypes
from ctypes import wintypes as w
import hashlib
import subprocess


class StartupInfo(ctypes.Structure):
    _fields_=[('cb',w.DWORD),('lpReserved',w.LPWSTR),('lpDesktop',w.LPWSTR),
              ('lpTitle',w.LPWSTR)]+[(n,w.DWORD) for n in
              ('dwX','dwY','dwXSize','dwYSize','dwXCountChars','dwYCountChars','dwFillAttribute','dwFlags')]+[
              ('wShowWindow',w.WORD),('cbReserved2',w.WORD),('lpReserved2',ctypes.c_void_p),
              ('hStdInput',w.HANDLE),('hStdOutput',w.HANDLE),('hStdError',w.HANDLE)]


class ProcessInfo(ctypes.Structure):
    _fields_=[('hProcess',w.HANDLE),('hThread',w.HANDLE),('dwProcessId',w.DWORD),('dwThreadId',w.DWORD)]


class BackgroundBrowser:
    """Small Popen-compatible owner for a process on a non-interactive desktop."""
    def __init__(self,args,profile):
        self.args=args;self.handle=None;self.desktop=None
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        k=self.kernel;u=self.user
        u.CreateDesktopW.argtypes=[w.LPCWSTR,w.LPCWSTR,ctypes.c_void_p,w.DWORD,w.DWORD,ctypes.c_void_p]
        u.CreateDesktopW.restype=w.HANDLE
        u.CloseDesktop.argtypes=[w.HANDLE];u.CloseDesktop.restype=w.BOOL
        k.CreateProcessW.argtypes=[w.LPCWSTR,w.LPWSTR,ctypes.c_void_p,ctypes.c_void_p,w.BOOL,w.DWORD,
                                  ctypes.c_void_p,w.LPCWSTR,ctypes.POINTER(StartupInfo),ctypes.POINTER(ProcessInfo)]
        k.CreateProcessW.restype=w.BOOL
        k.GetExitCodeProcess.argtypes=[w.HANDLE,ctypes.POINTER(w.DWORD)];k.GetExitCodeProcess.restype=w.BOOL
        k.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD];k.WaitForSingleObject.restype=w.DWORD
        k.TerminateProcess.argtypes=[w.HANDLE,w.UINT];k.TerminateProcess.restype=w.BOOL
        k.CloseHandle.argtypes=[w.HANDLE];k.CloseHandle.restype=w.BOOL
        name='YumiBrowser-'+hashlib.sha256(str(profile).encode()).hexdigest()[:16]
        # DESKTOP_CREATEWINDOW and the ordinary desktop rights. This desktop
        # is never made interactive (no SwitchDesktop call exists here).
        self.desktop=u.CreateDesktopW(name,None,None,0,0x01ff,None)
        if not self.desktop:raise ctypes.WinError(ctypes.get_last_error())
        startup=StartupInfo();startup.cb=ctypes.sizeof(startup);startup.lpDesktop='winsta0\\'+name
        info=ProcessInfo();command=ctypes.create_unicode_buffer(subprocess.list2cmdline(args))
        if not k.CreateProcessW(str(args[0]),command,None,None,False,subprocess.CREATE_NO_WINDOW,None,None,ctypes.byref(startup),ctypes.byref(info)):
            error=ctypes.get_last_error();self.release();raise ctypes.WinError(error)
        self.handle=info.hProcess;self.pid=info.dwProcessId;k.CloseHandle(info.hThread)

    def poll(self):
        if not self.handle:return 0
        code=w.DWORD()
        if not self.kernel.GetExitCodeProcess(self.handle,ctypes.byref(code)):raise ctypes.WinError(ctypes.get_last_error())
        return None if code.value==259 else code.value

    def wait(self,timeout=None):
        result=self.kernel.WaitForSingleObject(self.handle,0xffffffff if timeout is None else max(0,int(timeout*1000)))
        if result==258:raise subprocess.TimeoutExpired(self.args,timeout)
        if result==0xffffffff:raise ctypes.WinError(ctypes.get_last_error())
        return self.poll()

    def terminate(self):
        if self.poll() is None:self.kernel.TerminateProcess(self.handle,1)

    def release(self):
        if self.handle:self.kernel.CloseHandle(self.handle);self.handle=None
        if self.desktop:self.user.CloseDesktop(self.desktop);self.desktop=None

    def __del__(self):
        self.release()
