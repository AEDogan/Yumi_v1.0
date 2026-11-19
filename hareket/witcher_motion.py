"""A27 M18 (17 Kas): Witcher modelleri anime (Haru) hareket dinamigiyle.

Yalniz Witcher paketinde ve YUMI_WITCHER_ANIME_HAREKET!=0 iken etkin (varsayilan acik; '0' eski davranis).
Anime modellerinde hicbir fonksiyon sonuc degistirmez.

1. Dirsek mentesesi (anatomik eksen): Witcher iskeletlerinde ust kol yerel cercevesi kaynak kliplerin T-pozundan
   farkli dondurulmus (kadin modellerde ~24 derece, Geralt ~7). Klip dirsegi anatomik eksenin disinda bukuluyordu.
   `reference_twist`: hedef referans pozunda ust kol kendi ekseni etrafinda dondurulur; modelin anatomik mentesesi
   klibin (kaynak iskeletin) mentese eksenine oturur.
2. Oturma/kalkma kol IK'si (`seat_arm`): IK dirsek konumu ayni; ust kolun kendi ekseni etrafindaki donusu anatomik
   mentese IK bukulme duzlemine dik olacak sekilde secilir; on kol yalniz mentese etrafinda bukulur.
3. Klavikula: Witcher klavikulasi anime modellerinin ~3 kati uzun (Geralt 18,7 cm, Haru 6,2 cm); kliplerin omuz
   donusu kol kokunu 2-5 cm kaldiriyordu (Haru'da <1 cm). `scale_shoulders`: klip omuz donusu referansa gore
   SHOULDER_SCALE oranina kucultulur (Haru'daki kol koku hareketine denk). Oturma/kalkma klipleri haric.
"""
import math
import os
import numpy as np
from weakref import WeakKeyDictionary

SHOULDER_SCALE = .25  # yalniz yuruyus/bosta klipleri; oturma-kalkma (Sitting_*) klavikulasi olceklenmez (olcum: olceklemek koltukta omzu kaldiriyor)
REST_BEND_MIN = 10.  # derece; dinlenme pozunda bu kadar bukuk dirsek anatomik mentese verir


def enabled():
    # 18 Kas 01:10: kullanici canlida oturunca ellerin 180 derece donmesi + basparmak disa donuklugu gordu (tum Witcher); M18 KAPALI, yeniden calisilmadan acilmaz ('1' ile acilir).
    return os.environ.get('YUMI_WITCHER_ANIME_HAREKET', '0').strip() in ('1', 'true', 'evet', 'yes', 'on')


def is_witcher(data):
    # G-A2 (18 Kas): paket karakter.json "paket" alanindan (karakterler.witcher_mi)
    import karakterler
    return karakterler.witcher_mi(data)


def active(data):
    return data is not None and enabled() and is_witcher(data)


def _unit(v):
    n = float(np.linalg.norm(v)); return v / n if n > 1e-12 else v


def _rot(m):
    return m / np.linalg.norm(m, axis=0)


def axis_rotation(axis, angle):
    x, y, z = _unit(np.asarray(axis, float)); c, s = math.cos(angle), math.sin(angle); C = 1 - c
    return np.array([[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
                     [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
                     [z * x * C - y * s, z * y * C + x * s, c + z * z * C]])


def _signed(a, b, axis):
    a = _unit(a - axis * float(a @ axis)); b = _unit(b - axis * float(b @ axis))
    return math.atan2(float(np.cross(a, b) @ axis), float(np.clip(a @ b, -1, 1)))


# --- kaynak klibin mentese ekseni (kaynak dinlenme cercevesinde, kaynak dunya uzayi) ---
_SOURCE = WeakKeyDictionary()


def _source_world(clip, t):
    from vrm import rotation
    from vrma import slerp
    t = t % max(clip.duration, 1e-5); local = [m.copy() for m in clip.local]
    for node, path, times, values, mode in clip.channels:
        if path != 'rotation': continue
        i = max(0, min(len(times) - 1, int(np.searchsorted(times, t, side='right') - 1))); k = min(i + 1, len(times) - 1)
        dt = float(times[k] - times[i]); u = 0 if dt <= 0 else max(0, min(1, (t - times[i]) / dt))
        if mode == 'STEP': v = values[i]
        elif mode == 'CUBICSPLINE': v = values[3 * i + 1] if u < .5 else values[3 * k + 1]
        else: v = slerp(values[i], values[k], u)
        local[node][:3, :3] = rotation(v)
    world = np.tile(np.eye(4), (len(local), 1, 1))
    for i in clip.order: world[i] = world[clip.parents[i]] @ local[i] if i in clip.parents else local[i]
    return world


def source_hinge(clip, side):
    """Klibin dirsek mentese ekseni, kaynak iskeletin dinlenme (T) pozunda, kaynak dunya uzayinda (birim)."""
    cache = _SOURCE.get(clip)
    if cache is None: cache = {}; _SOURCE[clip] = cache
    if side in cache: return cache[side]
    names = [side + p for p in ('UpperArm', 'LowerArm', 'Hand')]
    result = None
    if all(n in clip.bones for n in names):
        a, b, c = [clip.bones[n] for n in names]; acc = np.zeros(3)
        r0 = _rot(clip.world[a, :3, :3])
        for t in np.linspace(0., max(clip.duration, 1e-3), 48, endpoint=False):
            w = _source_world(clip, t)
            u = w[b, :3, 3] - w[a, :3, 3]; f = w[c, :3, 3] - w[b, :3, 3]
            n = np.cross(u, f); s = float(np.linalg.norm(n) / (np.linalg.norm(u) * np.linalg.norm(f) + 1e-12))
            if s < math.sin(math.radians(8)): continue
            acc += s * (r0 @ _rot(w[a, :3, :3]).T @ (n / np.linalg.norm(n)))
        if np.linalg.norm(acc) > 1e-6: result = _unit(acc)
    if result is None:
        try:
            from natural_walk import load_walk
            src = load_walk().source
            if src is not clip: result = source_hinge(src, side)
        except Exception:
            result = None
    cache[side] = result
    return result


# --- modelin anatomik mentesesi (ust kol yerel cercevesinde) ---
_HINGE = WeakKeyDictionary()


def hinge_local(data, side, implied=None):
    """Anatomik dirsek mentesesi, ust kol yerel cercevesinde (model uzayi, birim). Dinlenme pozunda dirsek bukukse
    ondan; degilse `implied` (klibin dogurdugu eksen) iskeletin en yakin ana eksenine yapistirilir."""
    cache = _HINGE.get(data)
    if cache is None: cache = {}; _HINGE[data] = cache
    if side in cache: return cache[side]
    j = data.bones; a, b, c = j[side + 'UpperArm'], j[side + 'LowerArm'], j[side + 'Hand']
    R = _rot(data.rest[a, :3, :3])
    u = data.rest[b, :3, 3] - data.rest[a, :3, 3]; f = data.rest[c, :3, 3] - data.rest[b, :3, 3]
    n = np.cross(u, f); s = float(np.linalg.norm(n) / (np.linalg.norm(u) * np.linalg.norm(f) + 1e-12))
    if s >= math.sin(math.radians(REST_BEND_MIN)):
        h = _unit(R.T @ n); cache[side] = h; return h
    if implied is None: return None
    bone = _unit(R.T @ u)
    cands = [e * sg for e in np.eye(3) for sg in (1., -1.) if abs(float(e @ bone)) < .5]
    h = max(cands, key=lambda e: float(e @ implied))
    h = _unit(h - bone * float(h @ bone)); cache[side] = h
    return h


def reference_twist(clip, target, local, world, side, forward):
    """reference_pose icinde, ust kol yonu hizalandiktan sonra: ust kolu kendi ekseni etrafinda dondurerek modelin
    anatomik mentesesini klibin mentesesine oturtur. local/world yerinde degisir; yeni world dondurur."""
    j = target.bones
    if not all(side + p in j for p in ('UpperArm', 'LowerArm', 'Hand')): return world
    hs = source_hinge(clip, side)
    if hs is None: return world
    a = j[side + 'UpperArm']; b = j[side + 'LowerArm']
    want = _unit(target.flip.T @ hs)
    Ru = _rot(world[a, :3, :3])
    h = hinge_local(target, side, implied=_unit(Ru.T @ want))
    if h is None: return world
    bone = _unit(world[b, :3, 3] - world[a, :3, 3])
    have = Ru @ h
    if abs(float(want @ bone)) > .95: return world
    ang = _signed(have, want, bone)
    rot = axis_rotation(bone, ang) @ world[a, :3, :3]
    parent = target.parents.get(a)
    local[a][:3, :3] = np.linalg.solve(world[parent, :3, :3], rot) if parent is not None else rot
    return forward()


def scale_shoulders(rotations, data, reference_local):
    """Klip omuz (klavikula) donuslerini referansa gore SHOULDER_SCALE oranina kucultur (yerinde)."""
    from natural_walk import matrix_quaternion
    from vrm import rotation
    from vrma import slerp
    for side in ('left', 'right'):
        n = data.bones.get(side + 'Shoulder')
        if n is None or n not in rotations: continue
        ref = reference_local[n][:3, :3]
        q = matrix_quaternion(np.linalg.solve(ref, rotations[n]))
        rotations[n] = ref @ rotation(slerp(np.array([0., 0., 0., 1.]), q, SHOULDER_SCALE))


def seat_arm(model, world, side, shoulder, new_elbow, new_hand):
    """Oturma IK sonrasi ust kol + on kol: dirsek konumu IK'nin; ust kol ekseni etrafindaki donus anatomik mentese
    bukulme duzlemine dik olacak sekilde; on kol yalniz mentese etrafinda. world yerinde."""
    d = model.data; j = d.bones; physics = model.hair_springs.physics
    from vrm import aim
    a, b, c = j[side + 'UpperArm'], j[side + 'LowerArm'], j[side + 'Hand']
    elbow = world[b, :3, 3].copy()
    physics._rotate_subtree(world, a, aim(elbow - shoulder, new_elbow - shoulder))
    clip = None
    try:
        from natural_walk import load_walk
        clip = load_walk().source
    except Exception:
        pass
    implied = None
    if clip is not None and source_hinge(clip, side) is not None:
        implied = _unit(_rot(world[a, :3, :3]).T @ _unit(d.flip.T @ source_hinge(clip, side)))
    h = hinge_local(d, side, implied=implied)
    bone = _unit(world[b, :3, 3] - world[a, :3, 3])
    n = np.cross(new_elbow - shoulder, new_hand - new_elbow)
    if h is not None and np.linalg.norm(n) > 1e-6 * max(1., float(np.linalg.norm(new_elbow - shoulder))) ** 2:
        have = _rot(world[a, :3, :3]) @ h
        physics._rotate_subtree(world, a, axis_rotation(bone, _signed(have, _unit(n), bone)))
    # on kol: dinlenme yerel donusunden, mentese etrafinda hedefe
    neutral = world[d.parents[b], :3, :3] @ d.local[b][:3, :3]
    source = neutral @ np.linalg.solve(d.rest[b, :3, :3], d.rest[c, :3, 3] - d.rest[b, :3, 3])
    target = aim(source, new_hand - world[b, :3, 3]) @ neutral
    physics._rotate_subtree(world, b, target @ np.linalg.inv(world[b, :3, :3]))
