"""18 Kas (goz_el): Witcher paketinde derinlikte aynalanmis goz kapagi duzeltmesi (yalniz three-vrm cizimi).

Witcher kadin goz agi (`he_01_*`, goz malzemesi) yarim kuredir; iris UV (0.5, 0.5)'e denk gelen tepededir.
Yennefer ve Keira VRM'lerinde bu kapak kendi derinlik ekseninde (ham z) ters: tepe (iris) kirpiklerden UZAKTA,
basin icine bakiyor; onden yalniz goz akinin kenar dokusu (pembe/kirmizi) gorunuyor -> "gozler yok".
Model dosyalari legacy sha guveniyle kayitli oldugu icin dosya degistirilmez; three-vrm yuklemesinde o primitifin
konumlari kendi z araliginin ortasina gore aynalanir (normal/bicim hedefi z'si ve ucgen sarimi da cevrilir).

Kapi: yalniz Witcher paketi (seat_rig.witcher_package ile ayni yol kurali) ve yalniz olculen ters kapak.
Anime/retro modellerde bos liste doner; viewer'a giden yukleme cagrisi eskisiyle bit bit aynidir.
"""
import logging
from pathlib import Path
import numpy as np


def witcher_path(path):
    # G-A2 (18 Kas): karakter.json "paket" (seat_rig.witcher_package ile ayni kapi)
    import karakterler
    return path is not None and karakterler.witcher_mi(path)


def _image_name(g, material):
    try:
        tex = g['materials'][material]['pbrMetallicRoughness']['baseColorTexture']['index']
        return str(g['images'][g['textures'][tex]['source']].get('name', '')).casefold()
    except (KeyError, IndexError, TypeError):
        return ''


def mirrored_eye_caps(data):
    """[(mesh, primitive, plane_z), ...]: iris tepesi kirpiklerden uzaga bakan goz primitifleri (ham, deri oncesi z)."""
    g = data.g; out = []
    for mi, mesh in enumerate(g.get('meshes', [])):
        name = str(mesh.get('name', '')).casefold()
        if not (name.startswith('he_') or '_he_' in name):
            continue
        prims = mesh.get('primitives', [])
        kinds = [_image_name(g, p.get('material')) for p in prims]
        lash = [i for i, k in enumerate(kinds) if 'lash' in k]
        eyes = [i for i, k in enumerate(kinds) if 'eye' in k and not any(x in k for x in ('lash', 'shadow'))]
        if not lash or not eyes:
            continue
        lash_z = float(np.median(np.concatenate([data.array(prims[i]['attributes']['POSITION'])[:, 2] for i in lash])))
        for pi in eyes:
            attrs = prims[pi]['attributes']
            if 'TEXCOORD_0' not in attrs:
                continue
            pos = data.array(attrs['POSITION']); uv = data.array(attrs['TEXCOORD_0'])
            frac = uv - np.floor(uv); ters = []; cx = []
            for side in (pos[:, 0] < 0, pos[:, 0] >= 0):
                if side.sum() < 8:
                    break
                cx.append(float((pos[side, 0].min() + pos[side, 0].max()) / 2))
                idx = np.where(side)[0]; near = np.linalg.norm(frac[idx] - .5, axis=1)
                if near.min() > .03:
                    break
                apex = float(pos[idx[np.argmin(near)], 2]); z = pos[idx, 2]
                rim = float(z[np.argmax(np.abs(z - apex))])
                ters.append(np.sign(apex - rim) != np.sign(lash_z - rim) and abs(apex - rim) > 1e-3)
            if len(ters) == 2 and all(ters):
                # 18 Kas: yalniz z aynasi gozleri ~6 derece ice (sasi) baktiriyordu; ters kapak aslinda dikey eksende
                # 180 derece donmus -> viewer her gozu kendi merkezinde dondurur (x de cevrilir). cx = [sag (x<0), sol].
                out.append((mi, pi, float((pos[:, 2].min() + pos[:, 2].max()) / 2), cx[0], cx[1]))
    return out


def viewer_options(path):
    """three-vrm load() icin ek secenekler; Witcher disi ya da duzeltme gerekmiyorsa {}."""
    if not witcher_path(path):
        return {}
    try:
        from vrm import load_data
        caps = mirrored_eye_caps(load_data(str(Path(path).resolve())))
    except Exception:
        logging.getLogger(__name__).warning('Witcher goz kapagi olcumu yapilamadi', exc_info=True)
        return {}
    return {'mirrorEyes': [list(c) for c in caps]} if caps else {}
