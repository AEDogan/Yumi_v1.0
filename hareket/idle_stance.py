"""Boşta duruş katmanı (A28 dik gövde, A24 kol salınımı).

Idle_Loop / Idle_Talking_Loop klibinin gövde (omurga/göğüs/boyun/baş) ortalama eğimi
çıkarılır: gövde bağlama (dik) duruşa oturur, nefes salınımı aynen kalır. Kol
kemiklerinin klip ortalaması çevresindeki salınımı ARM_SWING oranına küçültülür.
Model başına bir kez: küçültülmüş klip örneklerinde el köşeleri ile gövde/etek
köşeleri arasındaki en küçük mesafe ölçülür; MARGIN altındaysa üst kol omuzdan
dışa açılır (en çok MAX_ABDUCT). Model adı/sabit model listesi kullanılmaz.
"""
import math
import numpy as np

CLIPS = ('Idle_Loop', 'Idle_Talking_Loop')
TRUNK = ('spine', 'chest', 'upperChest', 'neck', 'head')
ARM = ('Shoulder', 'UpperArm', 'LowerArm', 'Hand')
ARM_SWING = .3
# Gövde (göğüs) nefes salınımının kollara geçen kısmının ne kadarı geri alınır.
ARM_DECOUPLE = .8
# Gövde salınımı (ortalama çıkarıldıktan sonra kalan) oranı: alt omurga sallanması kolları
# ileri-geri taşır; göğüs (nefes) korunur.
TRUNK_SWING = {'spine': .7, 'chest': 1., 'upperChest': 1., 'neck': .8, 'head': .8}
MARGIN = .025  # metre (model uzayı)
MAX_ABDUCT = 14


def _quat(m):
    from natural_walk import matrix_quaternion
    return matrix_quaternion(m)


def _mean_rotation(mats):
    from vrm import rotation
    qs = [_quat(m) for m in mats]
    ref = qs[0]; acc = np.zeros(4)
    for q in qs: acc += q if float(q @ ref) >= 0 else -q
    return rotation(acc / max(float(np.linalg.norm(acc)), 1e-9))


def _scale_rotation(m, u):
    from vrm import rotation
    from vrma import slerp
    return rotation(slerp(np.array([0., 0., 0., 1.]), _quat(m), u))


def _family(d, root):
    s = {root}
    for node in d.order:
        if d.parents.get(node) in s: s.add(node)
    return s


class IdleStance:
    def __init__(self, data):
        self.data = data; self.stats = {}; self.points = None

    def _nodes(self):
        d = self.data; j = d.bones
        trunk = [j[n] for n in TRUNK if n in j]
        arm = [j[s + p] for s in ('left', 'right') for p in ARM if s + p in j]
        return trunk, arm

    def _rest_points(self):
        """Gövde/etek (kol ve baş ailesi dışı) ve el köşeleri, dinlenme konumunda, kanonik metre."""
        if self.points is not None: return self.points
        d = self.data; j = d.bones
        arms = set()
        for s in ('left', 'right'):
            if s + 'UpperArm' in j: arms |= _family(d, j[s + 'UpperArm'])
        head = _family(d, j['head']) if 'head' in j else set()
        hands = {s: _family(d, j[s + 'Hand']) for s in ('left', 'right') if s + 'Hand' in j}
        body = []; hand = {s: [] for s in hands}
        for part in d.parts:
            if part['skin'] is None or 'joints' not in part: continue
            nodes, inverse = d.skins[part['skin']]; used = np.unique(part['indices'])
            if not len(used): continue
            jn = nodes[part['joints'][used]]; w = part['weights'][used]
            skin = np.sum((d.rest[nodes] @ inverse)[part['joints'][used]] * w[:, :, None, None], axis=1)
            p = np.einsum('nij,nj->ni', skin, np.c_[part['pos'][used], np.ones(len(used))])[:, :3]
            other = (w * np.isin(jn, list(arms | head))).sum(1)
            keep = other < .05
            if keep.any():
                q = p[keep]
                if len(q) > 4000: q = q[:: len(q) // 4000 + 1]
                body.append(q)
            for s, fam in hands.items():
                m = (w * np.isin(jn, list(fam))).sum(1) > .5
                if m.any():
                    q = p[m]
                    if len(q) > 120: q = q[:: len(q) // 120 + 1]
                    hand[s].append(q)
        canon = lambda q: (q @ d.flip.T - d.origin) * d.scale
        self.points = (canon(np.concatenate(body)) if body else np.empty((0, 3)),
                       {s: canon(np.concatenate(v)) for s, v in hand.items() if v})
        return self.points

    def _forward(self, rotations):
        d = self.data; world = np.empty_like(d.rest)
        for i in d.order:
            local = d.local[i].copy()
            if i in rotations: local[:3, :3] = rotations[i]
            world[i] = (world[d.parents[i]] if i in d.parents else np.eye(4)) @ local
        return world

    def _prepare(self, name, clip):
        d = self.data; j = d.bones
        trunk, arm = self._nodes()
        samples = [clip.pose(t, d, loop=True)[0] for t in np.linspace(0., max(clip.duration, 1e-3), 24, endpoint=False)]
        means = {}
        for n in trunk + arm:
            mats = [s[n] for s in samples if n in s]
            if len(mats) == len(samples): means[n] = _mean_rotation(mats)
        names = {node: name for name, node in j.items()}
        st = {'means': means, 'trunk': {n: TRUNK_SWING.get(names[n], 1.) for n in trunk}, 'arm': set(arm), 'abduct': {}}
        self.stats[name] = st
        # Kol açısı: küçültülmüş örneklerde el-gövde/etek mesafesi.
        body, hands = self._rest_points()
        lower = {j[n] for n in ('hips', 'leftUpperLeg', 'rightUpperLeg', 'leftLowerLeg', 'rightLowerLeg', 'leftFoot', 'rightFoot', 'leftToes', 'rightToes') if n in j}
        hip_x = ((d.rest[j['hips'], :3, 3] @ d.flip.T - d.origin) * d.scale)[0]
        for side, hp in hands.items():
            if side + 'UpperArm' not in j or not len(body): continue
            hand = j[side + 'Hand']; upper = j[side + 'UpperArm']
            pts = []; pivots = []
            for s in samples[::2]:
                rot = {n: r for n, r in s.items() if n not in lower}
                self.adjust(rot, name)
                world = self._forward(rot)
                rel = world[hand] @ np.linalg.inv(d.rest[hand])
                model = (hp / d.scale + d.origin) @ d.flip
                q = (np.c_[model, np.ones(len(model))] @ rel.T)[:, :3]
                pts.append((q @ d.flip.T - d.origin) * d.scale)
                pivots.append((world[upper, :3, 3] @ d.flip.T - d.origin) * d.scale)
            allp = np.concatenate(pts); lo = allp.min(0) - .15; hi = allp.max(0) + .15
            near = body[np.all((body > lo) & (body < hi), axis=1)]
            sign = 1. if pivots[0][0] >= hip_x else -1.
            angle = 0
            if len(near):
                for angle in range(0, MAX_ABDUCT + 1):
                    a = math.radians(angle) * sign; c, sn = math.cos(a), math.sin(a)
                    rz = np.array([[c, -sn, 0.], [sn, c, 0.], [0., 0., 1.]])
                    dmin = np.inf
                    for p, pv in zip(pts, pivots):
                        r = (p - pv) @ rz.T + pv
                        dmin = min(dmin, float(np.linalg.norm(r[:, None, :] - near[None, :, :], axis=2).min()))
                    if dmin / d.scale >= MARGIN: break
            st['abduct'][side] = math.radians(angle) * sign
        return st

    def adjust(self, rotations, name, clip=None):
        """Klip yerel dönüşlerini yerinde değiştirir (gövde dik, kol salınımı küçük)."""
        st = self.stats.get(name)
        if st is None:
            if clip is None: return
            st = self._prepare(name, clip)
        d = self.data
        for n, mean in st['means'].items():
            r = rotations.get(n)
            if r is None: continue
            delta = mean.T @ r
            if n in st['trunk']: rotations[n] = d.local[n][:3, :3] @ _scale_rotation(delta, st['trunk'][n])
            else: rotations[n] = mean @ _scale_rotation(delta, ARM_SWING)

    def abduct(self, world, name, physics, weight):
        """Dünya pozunda: kolları gövde nefes salınımından büyük ölçüde ayırır (omuz eklemi gövdeyle
        hareket etmeyi sürdürür, kol yönü ortalama/dik gövdeye göre kalır) ve üst kolu dışa açar."""
        st = self.stats.get(name)
        if st is None or weight <= 0: return
        from vrma import slerp
        from vrm import rotation
        d = self.data; j = d.bones
        for side, angle in st['abduct'].items():
            upper = j[side + 'UpperArm']
            anchor = d.parents.get(j[side + 'Shoulder']) if side + 'Shoulder' in j else d.parents.get(upper)
            if anchor is not None:
                now = world[anchor, :3, :3] / np.linalg.norm(world[anchor, :3, :3], axis=0)
                ref = d.rest[anchor, :3, :3] / np.linalg.norm(d.rest[anchor, :3, :3], axis=0)
                q = _quat(ref @ now.T)
                turn = rotation(slerp(np.array([0., 0., 0., 1.]), q, ARM_DECOUPLE * weight))
                physics._rotate_subtree(world, upper, turn)
            if abs(angle) < 1e-6: continue
            a = angle * weight; c, s = math.cos(a), math.sin(a)
            rz = np.array([[c, -s, 0.], [s, c, 0.], [0., 0., 1.]])
            physics._rotate_subtree(world, upper, d.flip.T @ rz @ d.flip)
