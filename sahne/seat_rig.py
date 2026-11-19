"""Character-sized furniture fitting and continuous pelvis/foot/hand seat contacts."""
from dataclasses import dataclass
import math
import numpy as np
from motion import ik
from hand_pose import turn
from joint_limits import limit_rotation

def _unit(m):
    """18 Kas (goz_el/el): olcekli/kayik 3x3 matrisin en yakin donusu (SVD)."""
    u,_,v=np.linalg.svd(m);r=u@v
    if np.linalg.det(r)<0:u[:,-1]*=-1;r=u@v
    return r

def _forearm_rolls(model,side):
    """18 Kas (goz_el/el): onkol altindaki insansi olmayan kemikler (Witcher forearmRoll1/2, handRoll, elbowRoll),
    el alt agaci haric; burulma bunlara dirsekten bilege artan oranla dagitilir."""
    d=model.data;cache=d.__dict__.setdefault('_forearm_rolls',{})
    if side not in cache:
        physics=model.hair_springs.physics;b=d.bones[side+'LowerArm'];c=d.bones[side+'Hand']
        hand=set([c]+physics.children[c]);humanoid=set(d.bones.values())
        cache[side]=[n for n in d.order if n in physics.children[b] and n not in hand and n not in humanoid]
    return cache[side]

PALM_TARGET=(.5,-.85)  # (ice, asagi) kanonik; avuc uyluga/kucaga bakar, hafif ice
LAP_SPREAD=.24  # Witcher kucak hedefi: kalcadan yana koltuk genisligi orani (anime .16)
WRIST_YAW=25.  # Witcher kucaktaki el: bilegin one donusu siniri (derece)
def _lap_spread(model,f):
    """Witcher kucak hedefinin kalcadan yana uzakligi: oturma genisliginin .24'u, en az iki avuc genisligi (Geralt'in
    buyuk elleri .24'te hala ic ice geciyordu)."""
    r=model.rest_canonical;span=0.
    for s in ('left','right'):
        if s+'IndexProximal' in r and s+'LittleProximal' in r:span=max(span,float(np.linalg.norm(r[s+'IndexProximal']-r[s+'LittleProximal'])))
    return max(f.width*LAP_SPREAD,2.*span)
def _palm_down(model,world,side,goal,amount):
    """18 Kas (goz_el/el): kucaktaki elin avucunu asagi-ice cevirir; burulma onkol ekseni etrafinda, el tam, onkol
    burulma kemikleri dirsekten uzakliklarina gore geri cevrilir (net burulma dirsekte 0, bilekte tam)."""
    d=model.data;j=d.bones;physics=model.hair_springs.physics
    names=[side+p for p in ('LowerArm','Hand','IndexProximal','LittleProximal','MiddleProximal')]
    if 'hips' not in j or not all(n in j for n in names):return
    b,c,ix,li,mi=[j[n] for n in names]
    elbow=world[b,:3,3].copy();wrist=world[c,:3,3].copy();axis=wrist-elbow;length=float(np.linalg.norm(axis))
    if length<1e-9:return
    axis/=length
    # Kucak hedefine yakinlik: hedefte 1, kol boyunun yarisi uzakta 0.
    hand_c=(wrist@d.flip.T-d.origin)*d.scale;reach=length*d.scale*2.
    near=float(np.clip(1.-np.linalg.norm(hand_c-goal)/(.5*reach),0.,1.));near=near*near*(3-2*near)
    amount*=near
    if amount<=1e-4:return
    fwd=world[mi,:3,3]-wrist;fwd/=max(float(np.linalg.norm(fwd)),1e-9)
    radial=world[ix,:3,3]-world[li,:3,3];radial-=fwd*float(radial@fwd);radial/=max(float(np.linalg.norm(radial)),1e-9)
    # Avuc normali: kanonik +x tarafindaki el icin cross(fwd,radial), diger el icin cross(radial,fwd) (olculerek dogrulandi:
    # ayakta avuc uyluga bakar, basparmak avuc tarafinda).
    sg=1. if hand_c[0]>=((world[j['hips'],:3,3]@d.flip.T-d.origin)*d.scale)[0] else -1.
    fc=d.flip@fwd;rc=d.flip@radial;palm_c=np.cross(fc,rc) if sg>0 else np.cross(rc,fc)
    palm=d.flip.T@palm_c
    target=d.flip.T@np.array([-sg*PALM_TARGET[0],PALM_TARGET[1],0.])
    p=palm-axis*float(palm@axis);t=target-axis*float(target@axis)
    if np.linalg.norm(p)<1e-6 or np.linalg.norm(t)<1e-6:return
    # Onkol hedef yone (asagi) yaklastikca (kol sarkarken, kalkista) hedefin izdusumu belirsizlesir ve aci karede
    # 20-30 derece sicrar: onkol yatay degilse burulma azalir (izdusum boyu .5'te 0, .9'da tam).
    level=float(np.clip((np.linalg.norm(t)/max(float(np.linalg.norm(target)),1e-9)-.5)/.4,0.,1.))
    amount*=level*level*(3-2*level)
    if amount<=1e-4:return
    angle=math.atan2(float(axis@np.cross(p,t)),float(p@t))*amount
    angle=float(np.clip(angle,-math.radians(110),math.radians(110)))
    # Onkol kendi ekseni etrafinda doner (el yerel donusu degismez: solve_arms bilegi dinlenmeye 35 dereceyle sinirlar);
    # burulma kemikleri geri cevrilir, net burulma dirsekte 0, bilekte tam.
    physics._rotate_subtree(world,b,turn(axis,angle));done={b:angle}
    for n in _forearm_rolls(model,side):
        parent=d.parents[n];want=angle*float(np.clip((world[n,:3,3]-elbow)@axis/length,0.,1.))
        physics._rotate_subtree(world,n,turn(axis,want-done.get(parent,angle)));done[n]=want
    # Bilek: parmaklar ice (karsi ele) degil one baksin; avuc normali etrafinda en cok WRIST_YAW derece (solve_arms
    # bilek siniri 35). Iki elin parmaklari ic ice gecmez.
    palm=turn(axis,angle)@palm;fwd=world[mi,:3,3]-world[c,:3,3];fwd-=palm*float(fwd@palm)
    ahead=d.flip.T@np.array([0.,0.,1.]);ahead-=palm*float(ahead@palm)
    if np.linalg.norm(fwd)>1e-6 and np.linalg.norm(ahead)>1e-6:
        yaw=math.atan2(float(palm@np.cross(fwd,ahead)),float(fwd@ahead))
        limit=math.radians(WRIST_YAW)*amount;yaw=float(np.clip(yaw,-limit,limit))
        physics._rotate_subtree(world,c,turn(palm,yaw))

@dataclass
class SeatFit:
    item:dict
    scale:float
    height:float
    padding:float
    upper:float
    lower:float
    width:float
    depth:float
    pivot:np.ndarray
    yaw:float
    hip_offset:float=0.
    stand_distance:float=0.
    # 17 Kas (m12): clothed thigh envelope; 'padding' is the vertical lift under the thigh axis. Equal except Witcher.
    envelope:float=0.

def thigh_clearance(model):
    """Clothed thigh envelope, distinct from the narrow body collision proxy."""
    d=model.data
    if hasattr(d,'_seat_padding'):return d._seat_padding
    physics=model.hair_springs.physics;points,dominant=physics.samples;clearances=[]
    for side in ('left','right'):
        first=d.bones[side+'UpperLeg'];second=d.bones[side+'LowerLeg']
        start=d.rest[first,:3,3];axis=d.rest[second,:3,3]-start;squared=float(axis@axis)
        if squared<1e-12:continue
        selected=points[dominant==first];fraction=(selected-start)@axis/squared
        selected=selected[(fraction>-.10)&(fraction<.90)]
        if len(selected)<12:continue
        fraction=(selected-start)@axis/squared
        distance=np.linalg.norm(selected-start-fraction[:,None]*axis,axis=1)*d.scale
        clearances.append(float(np.percentile(distance,95)))
    proxy=max((c.radius*d.scale for c in physics.capsules if c.name.endswith('Thigh')),default=.06)
    r=model.rest_canonical;upper=float(np.mean([np.linalg.norm(r[s+'LowerLeg']-r[s+'UpperLeg']) for s in ('left','right')]))
    d._seat_padding=min(upper*.35,max([proxy,*clearances])+.015)
    return d._seat_padding

def _kabul_oturus(model):
    """Kullanıcı kabulü almış oturuş: A27 Witcher oturma düzeltmeleri uygulanmaz (G-A2: karakter.json
    "davranis": {"a27_oturma": false}; eskiden dosya adıyla tek modele bağlıydı)."""
    import karakterler
    return karakterler.davranis(model,'a27_oturma',True) is False

def seat_underside(model):
    """17 Kas (m12, A27 kok neden): underside under the thigh axis that really rests on the seat. thigh_clearance is
    the clothing envelope around the thigh (pouches, armour, skirts: 20-25 cm on Witcher models) and is still used
    for width/depth/behind-knee space; the seat height uses this one. Rest pose, rigid geometry dominated by the
    thigh (cloth parts and spring-weighted vertices excluded), behind the thigh axis inside a +-37 deg cone,
    95th percentile; bounded by the body proxy radius and the envelope."""
    d=model.data
    if hasattr(d,'_seat_underside'):return d._seat_underside
    envelope=thigh_clearance(model)
    canonical=lambda p:(np.asarray(p)@d.flip.T-d.origin)*d.scale
    springs=set(model.hair_springs.hair_nodes)|set(model.hair_springs.cloth_nodes)
    proxy=max((c.radius*d.scale for c in model.hair_springs.physics.capsules if c.name.endswith('Thigh')),default=.06)
    values=[]
    for side in ('left','right'):
        first=d.bones[side+'UpperLeg'];second=d.bones[side+'LowerLeg']
        a=canonical(d.rest[first,:3,3]);axis=canonical(d.rest[second,:3,3])-a;squared=float(axis@axis)
        if squared<1e-12:continue
        found=[]
        for part in d.parts:
            if part.get('kind')=='cloth' or part.get('skin') is None or 'joints' not in part:continue
            used=np.unique(part['indices']);nodes,inverse=d.skins[part['skin']]
            joints=nodes[part['joints'][used]];weights=part['weights'][used]
            selected=((weights*(joints==first)).sum(1)>=.5)&((weights*np.isin(joints,list(springs))).sum(1)<.05)
            if not selected.any():continue
            ids=used[selected]
            skin=np.sum((d.rest[nodes]@inverse)[part['joints'][ids]]*part['weights'][ids,:,None,None],axis=1)
            p=canonical(np.einsum('nij,nj->ni',skin,np.c_[part['pos'][ids],np.ones(len(ids))])[:,:3])
            fraction=(p-a)@axis/squared;keep=(fraction>.05)&(fraction<.75)
            offset=p[keep]-a-fraction[keep,None]*axis;back=-offset[:,2]
            found.append(back[(back>0)&(np.abs(offset[:,0])<back*.75)])
        found=np.concatenate(found) if found else np.empty(0)
        if len(found)>=12:values.append(float(np.percentile(found,95)))
    d._seat_underside=float(np.clip(max(values) if values else envelope,proxy,envelope))
    return d._seat_underside

def fit_chair(row,model,underside=None):
    d=model.data;r=model.rest_canonical;p=row['seat'];upper=np.mean([np.linalg.norm(r[s+'LowerLeg']-r[s+'UpperLeg']) for s in ('left','right')]);lower=np.mean([np.linalg.norm(r[s+'Foot']-r[s+'LowerLeg']) for s in ('left','right')])
    body=model.hair_springs.physics
    thigh=next((c.radius*d.scale for c in body.capsules if c.name=='leftThigh'),upper*.10)
    padding=thigh_clearance(model)
    if padding>upper*.5:raise ValueError('Bacak/kıyafet hacmi bu oturma düzenine güvenle sığmıyor.')
    # 17 Kas (m12): Witcher (Geralt haric, kabul edilmis oturus): seat height from the measured underside, not the
    # clothing envelope (the model hovered 8-16 cm, seat_sink then lowered the pelvis below the knees). The chair
    # grows instead; refine_seat_fit corrects the per-chair residual by chair height. Anime/retro: unchanged.
    lift=padding
    if underside is not None:lift=float(underside)
    elif row.get('role')=='chair' and witcher_package(model) and not _kabul_oturus(model):
        lift=getattr(d,'_seat_lift',{}).get(row['id'])
        if lift is None:lift=seat_underside(model)
    world=d.rest.copy();soles=model.ground.sample(world);floor=float(soles[:,1].min())
    ankle=float(np.mean([r[s+'Foot'][1] for s in ('left','right')])-floor)
    height=float(lower+ankle-lift);seat_height=max(.05,p['seat_height']-row['bounds']['min'][1]);scale=height/seat_height
    # Keep a leg-sized seat height. Deep seats that cannot fit at this height
    # are rejected below rather than lowering the pelvis into raised knees.
    height=scale*seat_height
    width=p['width']*scale;depth=p['depth']*scale;hips=abs(r['leftUpperLeg'][0]-r['rightUpperLeg'][0])
    if width<hips+thigh*2.3:raise ValueError('Koltuk karakterin kalça/bacak genişliğine uygun değil.')
    if depth<upper*.60 or depth>upper*1.85:raise ValueError('Koltuk derinliği karakterin uyluk ölçüsüne uygun değil.')
    forward=np.array(p['forward']);patch=np.array(p.get('outline',p['patch']));front=float(np.max(patch@forward));center=np.array(p['center'])
    # Leave space behind the knee; the pelvis is placed by thigh support,
    # rather than by the center of the chair's overall bounding box.
    support=max(upper*.60,upper-padding-.040)
    butt=front-support/scale;low=float(np.min(patch@forward));butt=max(low+.05*(front-low),min(front-.1*(front-low),butt))
    pivot=center+forward*(butt-float(center@forward));pivot[1]=row['bounds']['min'][1]
    yaw=math.degrees(math.atan2(float(forward[0]),float(forward[2])))
    hip_offset=float(r['hips'][1]-np.mean([r[s+'UpperLeg'][1] for s in ('left','right')]))
    stand_distance=max(float(upper),float(front-pivot@forward)*scale+padding+.025)
    if row['role']=='chair':
        bounds=row['bounds']
        footprint=np.array([[x,0.,z] for x in (bounds['min'][0],bounds['max'][0]) for z in (bounds['min'][2],bounds['max'][2])])
        stand_distance=max(stand_distance,float(np.max((footprint-pivot)@forward))*scale+thigh+.035+(float(row.get('foot_margin',0.)) if witcher_package(model) else 0.))
    return SeatFit(row,float(scale),height,float(lift),float(upper),float(lower),float(width),float(depth),pivot,yaw,hip_offset,stand_distance,float(padding))

def witcher_package(model):
    """17 Kas (kullanici karari): A27 oturma/kitap/yol/palto duzeltmeleri yalniz Witcher paketinde; anime/retro eski yol.
    G-A2 (18 Kas): paket karakter.json "paket" alanindan (karakterler.witcher_mi); klasor adi aranmaz."""
    import karakterler
    return karakterler.witcher_mi(model)

def seat_sink(scene,model,allow_raise=False,single=False):
    """17 Kas (A27): measured hover of the seated pose above the actual cushion.
    The pelvis height comes from a thigh clothing envelope (thigh_clearance); on layered game models
    (Witcher: pouches, armour, sheaths) that envelope is far wider than the underside that really rests
    on the cushion, so the whole character hovered 3-16 cm. A trial seated pose is skinned once and the
    lowest geometry under the pelvis/thighs (any mesh, cloth and spring meshes included, so nothing is
    pushed further into the cushion) is lowered onto the cushion top. Never raises."""
    d=model.data;rig=scene.rig;f=scene.fit;env=scene.contacts
    canonical=lambda p:(np.asarray(p)@d.flip.T-d.origin)*d.scale
    roots=('leftUpperLeg','rightUpperLeg','hips')
    if not hasattr(d,'_seat_sink_vertices'):
        rest_roots=np.array([canonical(d.rest[d.bones[n],:3,3]) for n in roots]);chosen=[]
        for index,part in enumerate(d.parts):
            if part.get('skin') is None or 'joints' not in part:continue
            used=np.unique(part['indices']);nodes,inverse=d.skins[part['skin']]
            skin=np.sum((d.rest[nodes]@inverse)[part['joints'][used]]*part['weights'][used,:,None,None],axis=1)
            p=canonical(np.einsum('nij,nj->ni',skin,np.c_[part['pos'][used],np.ones(len(used))])[:,:3])
            near=(p[:,1]>rest_roots[2,1]-.80)&(p[:,1]<rest_roots[2,1]+.10)&(np.abs(p[:,0]-rest_roots[2,0])<.45)
            if near.any():chosen.append((index,used[near]))
        d._seat_sink_vertices=chosen
    if not hasattr(d,'_seat_sink_rigid'):
        # 17 Kas (m12 aday2): per selected vertex, rigid (not a cloth part, spring weight < .3) and its mesh.
        springs=set(model.hair_springs.hair_nodes)|set(model.hair_springs.cloth_nodes);rigid=[]
        for index,ids in d._seat_sink_vertices:
            part=d.parts[index];nodes=d.skins[part['skin']][0]
            if part.get('kind')=='cloth':keep=np.zeros(len(ids),bool)
            else:keep=(part['weights'][ids]*np.isin(nodes[part['joints'][ids]],list(springs))).sum(1)<.3
            rigid.append((part.get('mesh',index),keep))
        d._seat_sink_rigid=rigid
    def trial(sink,only_rigid=False):
        world=np.array(model.world,dtype=float,copy=True);saved=(rig.weight,rig.phase,rig.sink)
        rig.weight=1.;rig.phase='idle';rig.sink=sink
        try:rig.apply(world,model)
        finally:rig.weight,rig.phase,rig.sink=saved
        joints=np.array([canonical(world[d.bones[n],:3,3]) for n in roots]);hip_points=[];thigh_points=[]
        for (index,ids),(_,keep) in zip(d._seat_sink_vertices,d._seat_sink_rigid):
            part=d.parts[index];nodes,inverse=d.skins[part['skin']]
            skin=np.sum((world[nodes]@inverse)[part['joints'][ids]]*part['weights'][ids,:,None,None],axis=1)
            p=canonical(np.einsum('nij,nj->ni',skin,np.c_[part['pos'][ids],np.ones(len(ids))])[:,:3])
            low=p[:,1]<joints[2,1]+.05
            if only_rigid:low&=keep
            hip=np.min(np.linalg.norm(p[:,None,[0,2]]-joints[None,:,[0,2]],axis=2),axis=1)<.10;thigh=np.zeros(len(p),bool)
            for side in ('left','right'):
                a_=canonical(world[d.bones[side+'UpperLeg'],:3,3])[[0,2]];b_=canonical(world[d.bones[side+'LowerLeg'],:3,3])[[0,2]];ab=b_-a_
                raw=(p[:,[0,2]]-a_)@ab/max(float(ab@ab),1e-9);t=np.clip(raw,0,1)
                thigh|=(np.linalg.norm(p[:,[0,2]]-(a_+t[:,None]*ab),axis=1)<.10)&(raw<.80)
            hip_points.append(p[low&hip]);thigh_points.append(p[low&thigh])
        return hip_points,thigh_points
    from furniture_scene import rotation
    triangles=np.concatenate([((part['pos']-f.pivot)@rotation(-f.yaw).T*f.scale)[part['indices'].reshape(-1,3)] for part in scene.asset.parts if not scene.desk or 'chair' in part['name'].casefold()])
    def lowest_gap(points,full=False):
        # Settled seat: character frame equals the seat frame. Vertical rays against the actual chair
        # triangles (highest surface under each point, up to 6 cm above it): the seatTop envelope only
        # covers a +-10 cm band around the nominal seat height and misses sloped lounge seats.
        points=np.concatenate(points) if points else np.empty((0,3))
        if not len(points):return None
        order=np.argsort(points[:,1])
        if full and len(order)>400:
            # 17 Kas (m11): not only the 400 lowest points. Thighs that dip into a raised front cushion edge are
            # not the lowest in height (Shani/no-27: -5.7 cm missed). Stride sample of the rest, bounded cost.
            rest=order[400:];points=points[np.r_[order[:400],rest[::max(1,len(rest)//2000)]]]
        else:points=points[order[:400]]
        lo=points[:,[0,2]].min(0)-.01;hi=points[:,[0,2]].max(0)+.01;xz=triangles[:,:,[0,2]]
        tri=triangles[np.all(xz.max(1)>=lo,axis=1)&np.all(xz.min(1)<=hi,axis=1)]
        a,b,c=tri[:,0],tri[:,1],tri[:,2]
        du=b[:,0]-a[:,0];dv=b[:,2]-a[:,2];eu=c[:,0]-a[:,0];ev=c[:,2]-a[:,2];det=du*ev-dv*eu;ok=np.abs(det)>1e-12
        if not ok.any():return None
        a,b,c,du,dv,eu,ev,det=a[ok],b[ok],c[ok],du[ok],dv[ok],eu[ok],ev[ok],det[ok];gaps=[]
        for start in range(0,len(points),64):
            p=points[start:start+64];px=p[:,None,0]-a[None,:,0];pz=p[:,None,2]-a[None,:,2]
            s=(px*ev-pz*eu)/det;t=(du*pz-dv*px)/det;inside=(s>=0)&(t>=0)&(s+t<=1)
            h=a[None,:,1]+s*(b[None,:,1]-a[None,:,1])+t*(c[None,:,1]-a[None,:,1])
            h=np.where(inside&(h<=p[:,None,1]+.06),h,-np.inf);top=h.max(1);hit=np.isfinite(top)
            if hit.any():gaps.append(float(np.min(p[hit,1]-top[hit])))
        return min(gaps) if gaps else None
    # 17 Kas (m11): Geralt keeps the accepted single pass (hip first, thighs only above 8 cm, cap .6 padding).
    kabul=_kabul_oturus(model)
    main_only=(allow_raise or single) and not kabul
    def measure(sink):
        hip_points,thigh_points=trial(sink,main_only)
        if main_only:
            # 17 Kas (m12): only the main body mesh under the pelvis (largest rigid vertex count there, ALL of its
            # primitives; aday1 took the single largest primitive, which on Shani was a torso piece 26 cm above the
            # seat). Loose garments (Morvran's coat hangs ~10 cm below the body at the seat) are lifted by
            # seat_contact_patches; letting them decide would put the body 4-6 cm above the cushion.
            sizes={}
            for (key,_),h,t in zip(d._seat_sink_rigid,hip_points,thigh_points):sizes[key]=sizes.get(key,0)+len(h)+len(t)
            if sizes and max(sizes.values()):
                best=max(sizes,key=sizes.get);chosen=[k for k,(key,_) in enumerate(d._seat_sink_rigid) if key==best]
                hip_points=[hip_points[k] for k in chosen];thigh_points=[thigh_points[k] for k in chosen]
        gap=lowest_gap(hip_points,not kabul)
        # Large gaps under the hip joints usually mean an open slot between seat and back cushions; then
        # the thighs on the seat pan decide. Others: thighs always count (Shani sank 6 cm into no-27 with
        # the hips 7 cm above it).
        if kabul and gap is not None and gap<=.08:return gap
        other=lowest_gap(thigh_points,not kabul)
        if other is not None:gap=other if gap is None else min(gap,other)
        return gap
    gap=measure(0.)
    if gap is None:return 0.
    if kabul:return float(np.clip(gap-.004,0.,f.padding*.6))
    # 17 Kas (m12): with allow_raise a negative result (penetration) raises the pelvis; single = one measurement
    # (refine_seat_fit turns it into chair height).
    if single:return float(np.clip(gap-.004,-.12,.30))
    low=-.03 if allow_raise else 0.
    # Sloped lounge seats (mid_century) need more than the old .6 padding cap (Ciri: 23 cm measured, 12 cm
    # applied, 14 cm hover). The settled pose is re-measured: lowering moves the lowest point along the slope.
    limit=max(f.padding,getattr(f,'envelope',0.) or 0.)*1.5;sink=float(np.clip(gap-.004,low,limit))
    for _ in range(2):
        again=measure(sink)
        if again is None or abs(again-.004)<.003:break
        sink=float(np.clip(sink+again-.004,low,limit))
    return sink

def refine_seat_fit(fit,asset,model):
    """17 Kas (m12, A27): Witcher (Geralt haric). The measured residual between the seated pose and the actual
    cushion (raised front edges, sloped pans, butt shape) is removed by the chair height, the thigh axis stays at
    knee height. Result is cached per model x chair; seat_sink then only trims the remainder."""
    if not witcher_package(model) or _kabul_oturus(model):return fit
    d=model.data;cache=d.__dict__.setdefault('_seat_lift',{});key=fit.item['id']
    if key in cache:return fit
    from types import SimpleNamespace
    best=fit;best_gap=None
    for _ in range(4):
        probe=SimpleNamespace(rig=SeatedRig(fit),fit=fit,asset=asset,desk=None,contacts=None,model=model)
        try:
            # aday2: the settled pose includes the sit/rise clearance curve (FurnitureContacts does the same);
            # without it the probe and the real pose differed by up to 10 cm (Shani).
            from furniture_scene import rotation
            from seat_clearance import fit_curve
            triangles=np.concatenate([((p['pos']-fit.pivot)@rotation(-fit.yaw).T*fit.scale)[p['indices'].reshape(-1,3)] for p in asset.parts])
            probe.rig.clearance_curve=fit_curve(probe,triangles)
            gap=seat_sink(probe,model,single=True)
        except (ValueError,IndexError,KeyError,TypeError,np.linalg.LinAlgError):break
        if best_gap is None or abs(gap)<abs(best_gap):best,best_gap=fit,gap
        if abs(gap)<=.005:break
        try:fit=fit_chair(fit.item,model,underside=fit.padding-gap)
        except ValueError:break
    cache[key]=best.padding
    return best

class SeatedRig:
    def __init__(self,fit):self.fit=fit;self.weight=0.;self.phase='idle';self.mode='lounge';self.sink=0.
    def apply(self,world,model):
        weight=float(np.clip(self.weight,0.,1.))
        if weight<=0:return
        d=model.data;physics=model.hair_springs.physics;f=self.fit
        from vrm import aim
        def canonical(node):return (world[node,:3,3]@d.flip.T-d.origin)*d.scale
        hips=d.bones['hips'];hip=canonical(hips);old_feet={side:canonical(d.bones[side+'Foot']) for side in ('left','right')}
        # The humanoid hips node is a rig root, not the thigh joint. Different
        # avatars place it above or below the femur attachment. Fit the actual
        # thigh centerline to the cushion, preserving the authored root offset.
        amount=(f.height+f.padding+f.hip_offset-hip[1])*weight
        amount-=getattr(self,'sink',0.)*weight
        forward_clearance=0.
        if hasattr(self,'clearance_curve'):
            weights,lifts,residual,forwards=self.clearance_curve
            amount+=float(np.interp(weight,weights,lifts))
            forward_clearance=float(np.interp(weight,weights,forwards))
        world[:,:3,3]+=d.flip.T@np.array([0.,amount/d.scale,forward_clearance/d.scale])
        for side in ('left','right'):
            a,b,c=[d.bones[side+p] for p in ('UpperLeg','LowerLeg','Foot')]
            hip,knee,foot=[world[n,:3,3].copy() for n in (a,b,c)];foot_rotation=world[c,:3,:3].copy()
            upper=float(np.linalg.norm(knee-hip));lower=float(np.linalg.norm(foot-knee))
            target=old_feet[side].copy();target[2]+=(f.stand_distance or f.upper)*weight
            raw=d.flip.T@(target/d.scale+d.origin)
            new_knee,new_foot=ik(hip,raw,upper,lower,d.flip.T@np.array([0.,0.,1.]),145)
            physics._rotate_subtree(world,a,aim(knee-hip,new_knee-hip))
            physics._rotate_subtree(world,b,aim(world[c,:3,3]-world[b,:3,3],new_foot-world[b,:3,3]))
            physics._rotate_subtree(world,c,foot_rotation@np.linalg.inv(world[c,:3,:3]))
        # Foot skinning can include shin weights: preserving ankle rotation
        # alone does not preserve the rendered sole height after bending knees.
        for _ in range(4):
            for side in ('left','right'):
                gap=float(model.ground.sample(world,side)[:,1].min())
                if abs(gap)<.0005:continue
                a,b,c=[d.bones[side+p] for p in ('UpperLeg','LowerLeg','Foot')]
                hip,knee,foot=[world[n,:3,3].copy() for n in (a,b,c)]
                orientation=world[c,:3,:3].copy()
                target=foot+d.flip.T@np.array([0.,-gap/d.scale,0.])
                middle,end=ik(hip,target,np.linalg.norm(knee-hip),np.linalg.norm(foot-knee),d.flip.T@np.array([0.,0.,1.]),145)
                physics._rotate_subtree(world,a,aim(knee-hip,middle-hip))
                physics._rotate_subtree(world,b,aim(world[c,:3,3]-world[b,:3,3],end-world[b,:3,3]))
                physics._rotate_subtree(world,c,orientation@np.linalg.inv(world[c,:3,:3]))
        # A small forward lean transfers weight while lowering/rising; the
        # settled lounge pose has a modest supported recline.
        spine=d.bones.get('spine');lean=.14*math.sin(math.pi*weight)-(.08 if self.mode=='lounge' else 0.)*weight
        if spine is not None:physics._rotate_subtree(world,spine,d.flip.T@turn(np.array([1.,0.,0.]),lean)@d.flip)
        speaking=getattr(model,'speaking_for_seat',False)
        style=getattr(model,'active_hand_style',model.hand_gesture)
        gesturing=bool(style or speaking)
        targets=model.conversation.arm_targets(model.rest_canonical,style) if gesturing else {}
        if weight>0:
            # 18 Kas (goz_el/el): Witcher'da kol IK sonucu (dirsek kutbu, onkol/el dinlenme burulmasi) ilk oturma
            # karesinde (agirlik 0,001) tam uygulaniyordu: ust kol 45, el 58-82 derece tek karede donuyordu. Klip pozundan
            # IK pozuna yerel donuslerle agirlik kadar gecilir; agirlik 1'de (oturus, kitap) sonuc aynidir. Anime: eski yol.
            arm_blend=None;witcher=witcher_package(model);lap_goals={}
            if weight<1. and witcher:
                arm_blend={}
                for side in ('left','right'):
                    for n in [d.bones[side+p] for p in ('UpperArm','LowerArm','Hand')]+_forearm_rolls(model,side):
                        arm_blend[n]=_unit(world[d.parents[n],:3,:3]).T@_unit(world[n,:3,:3])
            for side,sign in (('left',1),('right',-1)):
                a,b,c=[d.bones[side+p] for p in ('UpperArm','LowerArm','Hand')]
                shoulder,elbow,hand=[world[n,:3,3].copy() for n in (a,b,c)];hand_rotation=world[c,:3,:3].copy()
                sign=1 if canonical(a)[0]>=canonical(hips)[0] else -1
                # Chair depth is measured from its pivot, while avatars can
                # have authored torso offsets. Keep the lap in front of the
                # actual shoulder throughout lowering and rising.
                shoulder_canonical=canonical(a)
                # 18 Kas (goz_el/el): Witcher'da avuc asagi donunce iki elin parmaklari ic ice geciyordu (kemikler 1,7 cm);
                # eller uyluklarin ustune biraz aralanir. Anime: .16.
                goal=np.array([canonical(hips)[0]+sign*(_lap_spread(model,f) if witcher else f.width*.16),f.height+f.padding+(f.envelope or f.padding)+.06,shoulder_canonical[2]+f.upper*.50])
                if self.mode=='work' and hasattr(self,'keyboard_target'):
                    goal=self.keyboard_target.copy();goal[0]+=sign*self.hand_spacing
                selected=(model.conversation.variant%2==0)==(side=='left')
                active=gesturing and (selected or style in ('open_palm','shrug'))
                lap_goals[side]=goal.copy()
                pole=np.array([sign*.25,-1.,.35])
                if active and side+'Hand' in targets:
                    # Rebase the standing gesture on the actually seated
                    # shoulder, after pelvis shift and supported torso lean.
                    goal=canonical(a)+targets[side+'Hand']-model.rest_canonical[side+'UpperArm']
                    reach=float(np.linalg.norm(elbow-shoulder)+np.linalg.norm(hand-elbow))*d.scale
                    goal[1]=max(goal[1],f.height+f.padding+reach*.20)
                    goal[2]=max(goal[2],f.upper*.44)
                    if style=='hip':
                        goal[0]=canonical(hips)[0]+sign*min(f.width*.32,reach*.48)
                        pole=np.array([sign*.8,-.35,.1])
                    if self.mode=='work' and hasattr(self,'keyboard_target'):
                        # Lift an expressive hand clear of the keyboard/table;
                        # the resting hand remains at its fitted typing point.
                        goal[1]=max(goal[1],self.keyboard_target[1]+reach*.16)
                target=canonical(c)*(1-weight)+goal*weight;target=d.flip.T@(target/d.scale+d.origin)
                upper=float(np.linalg.norm(elbow-shoulder));lower=float(np.linalg.norm(hand-elbow))
                new_elbow,new_hand=ik(shoulder,target,upper,lower,d.flip.T@pole,135)
                from witcher_motion import active as _witcher_active
                if _witcher_active(d):
                    # A27 M18: anatomik dirsek mentesesi (ust kol burulmasi + on kol yalniz mentese etrafinda).
                    from witcher_motion import seat_arm
                    seat_arm(model,world,side,shoulder,new_elbow,new_hand)
                    for node,limit in ((a,155.),(b,134.)):
                        parent=world[d.parents[node],:3,:3]
                        bounded=parent@limit_rotation(d.local[node][:3,:3],np.linalg.solve(parent,world[node,:3,:3]),limit)
                        physics._rotate_subtree(world,node,bounded@np.linalg.inv(world[node,:3,:3]))
                    hand_rotation=world[b,:3,:3]@np.linalg.solve(d.rest[b,:3,:3],d.rest[c,:3,:3])
                    physics._rotate_subtree(world,c,hand_rotation@np.linalg.inv(world[c,:3,:3]))
                    parent=world[d.parents[c],:3,:3]
                    bounded=parent@limit_rotation(d.local[c][:3,:3],np.linalg.solve(parent,world[c,:3,:3]),35.)
                    physics._rotate_subtree(world,c,bounded@np.linalg.inv(world[c,:3,:3]))
                    continue
                target_rotation=aim(elbow-shoulder,new_elbow-shoulder)@world[a,:3,:3]
                physics._rotate_subtree(world,a,target_rotation@np.linalg.inv(world[a,:3,:3]))
                parent=world[d.parents[a],:3,:3]
                bounded=parent@limit_rotation(d.local[a][:3,:3],np.linalg.solve(parent,world[a,:3,:3]),155.)
                physics._rotate_subtree(world,a,bounded@np.linalg.inv(world[a,:3,:3]))
                neutral=world[d.parents[b],:3,:3]@d.local[b][:3,:3]
                source=neutral@np.linalg.solve(d.rest[b,:3,:3],d.rest[c,:3,3]-d.rest[b,:3,3])
                target_rotation=aim(source,new_hand-world[b,:3,3])@neutral
                physics._rotate_subtree(world,b,target_rotation@np.linalg.inv(world[b,:3,:3]))
                parent=world[d.parents[b],:3,:3]
                bounded=parent@limit_rotation(d.local[b][:3,:3],np.linalg.solve(parent,world[b,:3,:3]),134.)
                physics._rotate_subtree(world,b,bounded@np.linalg.inv(world[b,:3,:3]))
                hand_rotation=world[b,:3,:3]@np.linalg.solve(d.rest[b,:3,:3],d.rest[c,:3,:3])
                physics._rotate_subtree(world,c,hand_rotation@np.linalg.inv(world[c,:3,:3]))
                parent=world[d.parents[c],:3,:3]
                bounded=parent@limit_rotation(d.local[c][:3,:3],np.linalg.solve(parent,world[c,:3,:3]),35.)
                physics._rotate_subtree(world,c,bounded@np.linalg.inv(world[c,:3,:3]))
            if witcher:
                # 18 Kas (goz_el/el): Witcher dinlenme burulmasi oturusta eli yan yatiriyordu (avuc karna/yukari, basparmak
                # yukari-disa). Kucaktaki el avucu asagi-ice doner; el kucak hedefinden uzaklastikca (jest) ve sahne etkinligi
                # (kitap vb.) agirligi kadar azalir: konumla surekli, ani gecis yok. Kitapli oturus (etkinlik agirligi 1) aynidir.
                activity=getattr(model,'scenario_activity',None)
                amount=1.-float(np.clip(activity.weight,0.,1.)) if activity is not None else 1.
                if amount>0:
                    for side,goal in lap_goals.items():_palm_down(model,world,side,goal,amount)
            if arm_blend:
                from vrma import slerp
                from vrm import rotation
                from natural_walk import matrix_quaternion
                for node,before in arm_blend.items():
                    parent=_unit(world[d.parents[node],:3,:3]);after=parent.T@_unit(world[node,:3,:3])
                    local=rotation(slerp(matrix_quaternion(before),matrix_quaternion(after),weight))
                    physics._rotate_subtree(world,node,parent@local@_unit(world[node,:3,:3]).T)
            if style:
                model.hand_poses.apply(world,style,'left' if model.conversation.variant%2==0 else 'right',weight)

