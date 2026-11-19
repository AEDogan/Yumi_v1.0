"""Witcher ayakta dinlenme eli (18 Kas, goz_el/el ayakta2). Yalniz Witcher paketi (vrm.py cagirir; anime yolu cagirmaz).

Boşta/dinleme/yürüyüşte kol sarkarken el ve parmaklar referans fotoğraftaki rahat ele getirilir:
- Bilek: ön kolun düz devamı (el ekseni = ön kol ekseni, hafif ulnar + hafif fleksiyon); ön kol salınımı/kol açısı korunur.
- Parmaklar: dinlenme (bind) pozundaki avuç düzlemi açılımı %30'una indirilir (parmaklar yakın), kıvrım
  işaretten serçeye artar (MCP/PIP/DIP); oyun iskeletinin bind kıvrımı (Yennefer'de ~45°) dikkate alınmaz.
- Başparmak (el3b): işarete yapışık değil, eli izleyip aşağı sarkar; sabit yönler THUMB_DIRS + roll kemiği izler.
Ağırlık çağıran tarafta yumuşak (0,35 s) değişir; jest/konuşma/el sallama/dans/oturma/etkinlikte 0.
Hesap dünya (model) uzayında; flip (y ekseni etrafında 180°) dönüş olduğundan çapraz çarpımlar korunur."""
import math
import numpy as np

WRIST_ULNAR = (5., 14.)  # derece, el ekseni ön kola göre serçe tarafına: en az / en çok (ön kol öne eğikse el dikeye yaklaşır)
WRIST_FLEX = 4.       # derece, avuç tarafına
SPREAD = .3          # bind açılımının kalan oranı
CURL = {'Index': (12., 22., 10.), 'Middle': (17., 29., 12.), 'Ring': (22., 36., 15.), 'Little': (27., 43., 17.)}
# Başparmak (el3b, 19 Kas): işarete yapışık değil; eli izleyip aşağı sarkar, hafif öne/dışa açık, arada ~bir parmak boşluk,
# ucu işaret orta boğumu hizasında. Kemik yönleri el çerçevesinde (ileri f, radyal r, avuç tarafı p) sabit.
THUMB_DIRS = ((.97, .17, .20), (.98, .12, .14), (.97, .10, .20))
POSE_FINGERS = False  # el3b (kullanıcı 19 Kas 00:28): dört parmak eski haline (animasyondan gelir), yalnız başparmak + bilek
THUMB_ROLL = .5  # başparmak kökü yardımcı kemiği (roll) metakarp dönüşünün bu kadarını izler
FADE = .35


def _unit(v):
    return v / max(float(np.linalg.norm(v)), 1e-12)


class RestHands:
    def __init__(self, data, physics):
        self.data = data; self.physics = physics; self.weight = 0.; self.clock = None; self.sides = {}
        d = data; j = d.bones
        P = lambda n: d.rest[j[n], :3, 3]
        hips_x = (P('hips') @ d.flip.T)[0]
        for side in ('left', 'right'):
            need = [side + n for n in ('Hand', 'LowerArm', 'IndexProximal', 'MiddleProximal', 'LittleProximal')]
            if not all(n in j for n in need): continue
            sign = 1. if (P(side + 'Hand') @ d.flip.T)[0] >= hips_x else -1.
            hand = P(side + 'Hand'); f = _unit(P(side + 'MiddleProximal') - hand)
            r = P(side + 'IndexProximal') - P(side + 'LittleProximal'); r = _unit(r - f * (r @ f))
            p = _unit(np.cross(f, r)) * sign
            fingers = {}
            for name in CURL:
                chain = [j.get(side + name + l) for l in ('Proximal', 'Intermediate', 'Distal')]
                if any(n is None for n in chain): continue
                v = _unit(d.rest[chain[1], :3, 3] - d.rest[chain[0], :3, 3]); s = v - p * (v @ p)
                fingers[name] = (chain, math.atan2(float(s @ r), float(s @ f)), self._tip_offset(chain[1], chain[2]))
            labels = ('Proximal', 'Intermediate', 'Distal') if d.legacy else ('Metacarpal', 'Proximal', 'Distal')
            thumb = [j.get(side + 'Thumb' + l) for l in labels]
            thumb = (thumb, self._tip_offset(thumb[1], thumb[2])) if all(n is not None for n in thumb) else None
            humanoid = set(j.values()); ch = [c for c, par in d.parents.items() if par == j[side + 'Hand']]
            roll = [c for c in ch if c not in humanoid and 'thumb' in str(d.nodes[c].get('name', '')).lower()]
            self.sides[side] = {'sign': sign, 'fingers': fingers, 'thumb': thumb, 'roll': roll}

    def _tip_offset(self, prev, last):
        d = self.data
        return np.linalg.solve(d.rest[last, :3, :3], d.rest[last, :3, 3] - d.rest[prev, :3, 3])

    def step(self, t, active):
        """Ağırlığı zamana göre hedefe yaklaştırır (yumuşak giriş/çıkış)."""
        dt = 0. if self.clock is None else max(0., min(.1, t - self.clock)); self.clock = t
        goal = 1. if active else 0.
        if self.weight < goal: self.weight = min(goal, self.weight + dt / FADE)
        elif self.weight > goal: self.weight = max(goal, self.weight - dt / FADE)
        return self.weight * self.weight * (3 - 2 * self.weight)

    def _rotate(self, world, node, turn):
        self.physics._rotate_subtree(world, node, turn)

    def _pose(self, world, side):
        from vrm import aim
        d = self.data; j = d.bones; st = self.sides[side]; sign = st['sign']
        X = lambda n: world[n, :3, 3]
        hand = j[side + 'Hand']
        a = _unit(X(hand) - X(j[side + 'LowerArm']))
        def frame():
            f = _unit(X(j[side + 'MiddleProximal']) - X(hand))
            r = X(j[side + 'IndexProximal']) - X(j[side + 'LittleProximal']); r = _unit(r - f * (r @ f))
            return f, r, _unit(np.cross(f, r)) * sign
        f, r, p = frame()
        pa = _unit(p - a * (p @ a)); ra = _unit(r - a * (r @ a))
        down = np.array([0., -1., 0.])
        best = math.degrees(math.atan2(-float(ra @ down), float(a @ down)))  # el eksenini en dikey yapan ulnar açı
        ulnar = math.radians(min(WRIST_ULNAR[1], max(WRIST_ULNAR[0], best)))
        goal = _unit(math.cos(ulnar) * a - math.sin(ulnar) * ra + math.tan(math.radians(WRIST_FLEX)) * pa)
        self._rotate(world, hand, aim(f, goal))
        f, r, p = frame()
        for name, (chain, spread, tip) in (st['fingers'].items() if POSE_FINGERS else ()):
            phi = spread * SPREAD; straight = _unit(math.cos(phi) * f + math.sin(phi) * r)
            total = 0.
            for k, node in enumerate(chain):
                total += math.radians(CURL[name][k])
                want = math.cos(total) * straight + math.sin(total) * p
                cur = X(chain[k + 1]) - X(node) if k < 2 else world[node, :3, :3] @ tip
                self._rotate(world, node, aim(cur, want))
        if st['thumb'] is not None:
            chain, tip = st['thumb']
            before = world[chain[0], :3, :3].copy()
            for k, node in enumerate(chain):
                c = THUMB_DIRS[k]; want = c[0] * f + c[1] * r + c[2] * p
                cur = X(chain[k + 1]) - X(node) if k < 2 else world[node, :3, :3] @ tip
                self._rotate(world, node, aim(cur, want))
            if st['roll']:
                # başparmak kökünün eti roll kemiğine de bağlı; dönmezse et gerilip çıkıntı yapar
                from vrma import slerp
                from natural_walk import matrix_quaternion
                from vrm import rotation
                delta = world[chain[0], :3, :3] @ np.linalg.inv(before)
                half = rotation(slerp(matrix_quaternion(np.eye(3)), matrix_quaternion(delta), THUMB_ROLL))
                for node in st['roll']: self._rotate(world, node, half)

    def apply(self, world, weight):
        if weight <= 0. or not self.sides: return
        target = world.copy()
        for side in self.sides: self._pose(target, side)
        if weight >= 1.:
            world[:] = target; return
        from vrma import slerp
        from natural_walk import matrix_quaternion
        from vrm import rotation
        d = self.data; nodes = set()
        for side, st in self.sides.items():
            nodes.add(d.bones[side + 'Hand'])
            if POSE_FINGERS:
                for chain, _, _ in st['fingers'].values(): nodes.update(chain)
            if st['thumb'] is not None: nodes.update(st['thumb'][0])
            nodes.update(st['roll'])
        for node in d.order:
            if node not in nodes: continue
            par = d.parents[node]
            cur = np.linalg.solve(world[par, :3, :3], world[node, :3, :3])
            tgt = np.linalg.solve(target[par, :3, :3], target[node, :3, :3])
            local = rotation(slerp(matrix_quaternion(cur), matrix_quaternion(tgt), weight))
            self._rotate(world, node, (world[par, :3, :3] @ local) @ np.linalg.inv(world[node, :3, :3]))
