"""A31 Katman 1 (17 Kas): oturma modunda etek/palto yay zincirlerinin dokumu.

Pisirme yok, canli kumas simulasyonu yok: yay calisma zamaninin (three-vrm) sonucunu oturma agirligiyla harmanli,
durumsuz ve belirlenimci olarak yerlestirir -> her oturusta ayni bicim. Zincir eklemleri koku-ucu sirasiyla:
  1) yercekimi: parca yonu asagiya cekilir (agirlik x GRAVITY), boy korunur;
  2) destek: uyluk (bind pozunda beden yuzeyinden olculmus 8x16 kesit yaricapi; disari dogru itilir), iki uyluk arasi
     'hamak' (kasigi orter) ve minder ustu (yukari); her geciste parca boyu kokunden geri kurulur (PASSES gecis);
  3) baldir kapsulleri onunden itilir.
Yalniz kalca/uyluk/bel kokenli etek-palto zincirleri; canta/hancer/madalyon/ip/gogus/sac dokunulmaz.
Geri donus: YUMI_OTUR_DOKUM=0 ya da model listede degilse hicbir sey yapmaz (bugunku davranis).
Model kaynagi, VRM, agirliklar degismez; yalniz o karenin eklem donusleri.
"""
import os,time
from pathlib import Path
import numpy as np

# Model basina acilir (VRM dosya adi govdesi, kucuk harf). Geralt oturusu kullanici kabulu: listede yok.
# 17 Kas olcumu (work/a31/olcum/tablo.md): yalniz hicbir olcusu kotulesmeyenler acik. Vita/Vivi (govde nufuzu +3 cm),
# Eddy (govde nufuzu +3 cm, kenar uzamasi), Lyra (pelerin kenar uzamasi 0->408) ayar bekliyor: kapali.
# 17 Kas (ikinci tur, kullanici kurali): anime modellere HIC dokunulmaz -> yalniz Witcher paketi; 'hepsi' de anime'yi acmaz.
ENABLED=set()  # Shani-Dugun artik goruntu/seated_skirt.py (kose dokumu): zincir dokumu etegi tepsi gibi yana yayiyordu
GRAVITY=.85;MARGIN=.012;HAMMOCK=.45;REFRESH=.5;PASSES=2
SKIRT_WORDS=('skirt','dress','etek','coat','cape','tasset','doublet','robe','cloth','upperleg')
EXCLUDE_WORDS=('bag','dagger','scabbard','medalion','medallion','pendant','rope','bust','hood','tail','hair','ribbon','string','sword','belt')

def enabled(springs):
    if os.environ.get('YUMI_OTUR_DOKUM','1')=='0':return False
    if not _witcher(springs):return False
    stem=Path(str(getattr(springs.data,'path','') or '')).stem.casefold()
    return stem in ENABLED or os.environ.get('YUMI_OTUR_DOKUM')=='hepsi'

def _witcher(springs):
    """seat_rig.witcher_package ile ayni kural (model nesnesi yerine yay verisinden; karakter.json "paket")."""
    import karakterler
    return karakterler.witcher_mi(springs)

def _setup(springs):
    d=springs.data;human=set(d.bones.values())
    roots={d.bones.get(k) for k in ('hips','spine','leftUpperLeg','rightUpperLeg')}-{None}
    pairs={}
    for group,nodes,kind in springs.chains:
        for node in nodes:
            if node not in springs.cloth_nodes:continue
            name=(kind+' '+d.nodes[node].get('name','')).casefold()
            if any(w in name for w in EXCLUDE_WORDS):continue
            ancestor=node
            while ancestor in d.parents and ancestor not in human:ancestor=d.parents[ancestor]
            if ancestor not in roots:continue
            if not any(w in name for w in SKIRT_WORDS) and node not in springs.skirt_nodes:continue
            pairs[node]=group.get('tipNode',d.nodes[node]['children'][0])
    if not pairs:return None
    order={n:i for i,n in enumerate(d.order)}
    level={}
    for node in sorted(pairs,key=order.get):
        a=d.parents.get(node);k=0
        while a is not None:
            if a in pairs:k=level[a]+1;break
            a=d.parents.get(a)
        level[node]=k
    levels=[np.array(sorted([n for n in pairs if level[n]==k],key=order.get),int) for k in range(max(level.values())+1)]
    # Affected subtree, rebuilt from locals by hierarchy depth (batched).
    children={}
    for n,p in d.parents.items():children.setdefault(p,[]).append(n)
    affected=set()
    stack=list(pairs)
    while stack:
        n=stack.pop()
        if n in affected:continue
        affected.add(n);stack.extend(c for c in children.get(n,[]) if c not in human)
    depth={}
    for n in sorted(affected,key=order.get):
        p=d.parents.get(n);depth[n]=depth[p]+1 if p in affected else 0
    rebuild=[np.array(sorted([n for n in affected if depth[n]==k],key=order.get),int) for k in range(1,max(depth.values())+1)] if depth else []
    rebuild=[r for r in rebuild if len(r)]
    rebuild_parents=[np.array([d.parents[n] for n in r],int) for r in rebuild]
    tips=[np.array([pairs[n] for n in lv],int) for lv in levels]
    affected=np.array(sorted(affected,key=order.get),int);slot={int(n):i for i,n in enumerate(affected)}
    return {'levels':levels,'tips':tips,'affected':affected,'parents':np.array([d.parents.get(int(n),-1) for n in affected],int),
            'rebuild':[(r,p,np.array([slot[int(n)] for n in r],int)) for r,p in zip(rebuild,rebuild_parents)],
            'level_slots':[np.array([slot[int(n)] for n in lv],int) for lv in levels],
            'drape_slots':np.array([slot[int(n)] for lv in levels for n in lv],int),
            'root_nodes':np.array([n for n in affected if depth[int(n)]==0],int),
            'root_parents':np.array([d.parents[int(n)] for n in affected if depth[int(n)]==0],int),
            'root_slots':np.array([slot[int(n)] for n in affected if depth[int(n)]==0],int),
            'level_parents':[np.array([d.parents[int(n)] for n in lv],int) for lv in levels],
            'profile':_thigh_profiles(springs)}

def _thigh_profiles(springs):
    """Bind-pose radius of the occupied thigh surface (body, not flexible cloth), 8 axial x 16 angular bins, per side."""
    d=springs.data;flex=set(springs.cloth_nodes)|set(springs.skirt_nodes)|set(springs.hair_nodes);human=set(d.bones.values());out={}
    for side in ('left','right'):
        upper=d.bones.get(side+'UpperLeg');lower=d.bones.get(side+'LowerLeg')
        if upper is None or lower is None:return None
        owners=set()
        for n in range(len(d.nodes)):
            a=n
            while a in d.parents and a not in human:a=d.parents[a]
            if a==upper and n not in flex:owners.add(n)
        A=d.rest[upper,:3,3];B=d.rest[lower,:3,3];axis=B-A;length=float(np.linalg.norm(axis));u=axis/max(length,1e-9)
        e1=np.cross(u,[0.,0.,1.]);e1=e1/max(np.linalg.norm(e1),1e-9) if np.linalg.norm(e1)>1e-6 else np.cross(u,[1.,0.,0.])/np.linalg.norm(np.cross(u,[1.,0.,0.]))
        e2=np.cross(u,e1);table=[[[] for _ in range(16)] for _ in range(8)]
        for part in d.parts:
            if part.get('skin') is None or 'joints' not in part or part['kind'] in ('hair','face'):continue
            nodes,inverse=d.skins[part['skin']];mapped=nodes[part['joints']]
            mass=np.sum(part['weights']*np.isin(mapped,list(owners)),axis=1)
            flexmass=np.sum(part['weights']*np.isin(mapped,list(flex)),axis=1)
            ids=np.intersect1d(np.flatnonzero((mass>.5)&(flexmass<.1)),np.unique(part['indices']))
            if part['kind']=='cloth':ids=ids[:0] if flexmass.max()>.3 else ids
            if not len(ids):continue
            skin=np.sum((d.rest[nodes]@inverse)[part['joints'][ids]]*part['weights'][ids,:,None,None],axis=1)
            p=np.einsum('nij,nj->ni',skin,np.c_[part['pos'][ids],np.ones(len(ids))])[:,:3]-A
            f=p@u/length;r=p-np.outer(p@u,u);dist=np.linalg.norm(r,axis=1);ang=np.arctan2(r@e2,r@e1)
            fb=np.clip((f*8).astype(int),0,7);ab=((ang+np.pi)/(2*np.pi)*16).astype(int)%16;keep=(f>-.05)&(f<1.05)
            for i in np.flatnonzero(keep):table[fb[i]][ab[i]].append(dist[i])
        base=springs.physics.capsules[[c.name for c in springs.physics.capsules].index(side+'Thigh')].radius
        radius=np.array([[np.percentile(c,90) if len(c)>=3 else np.nan for c in row] for row in table])
        radius=np.where(np.isfinite(radius),np.clip(radius,base*.8,base*1.7),base)
        out[side]=(upper,lower,e1,e2,radius*d.scale)
    return out

def _project(p,a,L,thighs,seat):
    """One constraint pass: thighs radially (measured cross-section), hammock and cushion vertically; then the
    segment length from its anchor is restored."""
    up=np.array([0.,1.,0.])
    for A,ax,ax2,to_bind,e1,e2,radius,lat in thighs:
        f=(p-A)@ax/ax2;fc=np.clip(f,0,1);c=A+fc[:,None]*ax;rv=p-c;dist=np.linalg.norm(rv,axis=1)
        rb=rv@to_bind.T;ab=(((np.arctan2(rb@e2,rb@e1)+np.pi)/(2*np.pi)*16).astype(int))%16
        fb=np.clip((fc*8).astype(int),0,7);r=radius[fb,ab]+MARGIN
        # Cloth coming from above (anchor over the axis) that fell into or under the thigh rests on its top side.
        # A segment from above that passed through (tip under the thigh, inside its width) is folded onto the top.
        ca=A+np.clip((a-A)@ax/ax2,0,1)[:,None]*ax;above=(a-ca)@up>0;vert=rv@up
        through=above&(vert<0)&(np.abs(rv@lat)<r);rv=np.where(through[:,None],rv-2*vert[:,None]*up,rv)
        inside=((dist<r)|through)&(f>-.05)&(f<1.02)&((rv@up>-.3*r)|above)&(dist>1e-6)
        p=np.where(inside[:,None],c+rv/np.maximum(dist,1e-9)[:,None]*r[:,None],p)
    if len(thighs)==2:
        (A1,ax1,q1,_,_,_,R1,lat),(A2,ax2_,q2,_,_,_,R2,_)=thighs
        f1=np.clip((p-A1)@ax1/q1,0,1);f2=np.clip((p-A2)@ax2_/q2,0,1);c1=A1+f1[:,None]*ax1;c2=A2+f2[:,None]*ax2_
        l1=(p-c1)@lat;l2=(p-c2)@lat;between=(l1*l2<0)&(f1<.98)&(f2<.98)
        t1=c1[:,1]+R1.max(1)[np.clip((f1*8).astype(int),0,7)]*.8;t2=c2[:,1]+R2.max(1)[np.clip((f2*8).astype(int),0,7)]*.8
        h=np.minimum(t1,t2)-HAMMOCK*np.minimum(np.abs(l1),np.abs(l2))
        lift=between&(p[:,1]<h)&(p[:,1]>np.minimum(c1[:,1],c2[:,1])-.08)
        p[lift,1]=h[lift]
    if seat is not None:
        # Cushion only: the seat-band field also holds arm/back triangles; cloth must not climb onto them.
        field,matrix,height,width=seat;local=p@matrix[:3,:3].T+matrix[:3,3];top,valid=field.sample(local)
        y=top-matrix[1,3]+MARGIN;lift=valid&(np.abs(top-height)<.04)&(np.abs(local[:,0])<width*.5)&(p[:,1]<y)&(p[:,1]>y-.25)
        p[lift,1]=y[lift]
    v=p-a;return a+v/np.maximum(np.linalg.norm(v,axis=1),1e-9)[:,None]*L[:,None]

def solve(springs,world,environment):
    weight=float(getattr(environment.scene.rig,'weight',0.)) if environment is not None else 0.
    if weight<=.001 or environment.scene.desk or not enabled(springs):
        springs._drape_cache=None;return
    started=time.perf_counter()
    if not hasattr(springs,'_drape'):springs._drape=_setup(springs)
    setup=springs._drape
    if setup is None or setup['profile'] is None:return
    d=springs.data;flip=d.flip;scale=d.scale;origin=d.origin
    canon=lambda x:(x@flip.T-origin)*scale
    local=np.linalg.solve(world[setup['parents']],world[setup['affected']])
    # The drape is a function of the seated body pose: re-solve at REFRESH (every frame-ish while lowering/rising),
    # otherwise reuse the solved joint locals (one batched rebuild; cloth follows hips/thighs rigidly in between).
    cache=getattr(springs,'_drape_cache',None)
    if cache is not None and started-cache['t']<(REFRESH if weight>=.999 else 1/30) and abs(weight-cache['w'])<.08:
        local[setup['drape_slots']]=cache['local'];_rebuild(world,local,setup,True)
        springs.drape_stats={'ms':round((time.perf_counter()-started)*1000,3),'joints':len(setup['drape_slots']),'weight':round(weight,3),'cached':True}
        return
    up=np.array([0.,1.,0.]);thighs=[];ph=springs.physics
    for side,(upper,lower,e1,e2,radius) in setup['profile'].items():
        A=canon(world[upper,:3,3]);B=canon(world[lower,:3,3]);ax=B-A
        # Canonical direction -> bind-pose direction of this thigh (selects the measured angular column).
        to_bind=np.linalg.solve(world[upper,:3,:3]@np.linalg.inv(d.rest[upper,:3,:3]),flip.T)
        lat=np.cross(up,ax);lat/=max(np.linalg.norm(lat),1e-9)
        thighs.append((A,ax,max(float(ax@ax),1e-12),to_bind,e1,e2,radius,lat))
    fit=environment.scene.fit;seat=(environment.fields[0],environment.matrix,fit.height,fit.width) if environment.fields else None
    shins=[i for i,c in enumerate(ph.capsules) if c.name in ('leftShin','rightShin')]
    ph.update(world);S=canon(ph.starts[shins]);E=canon(ph.ends[shins]);RS=ph.radii[shins]*scale+MARGIN
    hip=canon(world[d.bones['hips'],:3,3]);g=GRAVITY*weight;moved=0
    for k,(nodes,tips) in enumerate(zip(setup['levels'],setup['tips'])):
        if k:_rebuild(world,local,setup)
        a=canon(world[nodes,:3,3]);t=canon(world[tips,:3,3]);v=t-a;L=np.linalg.norm(v,axis=1);ok=L>1e-6
        dir0=v/np.maximum(L,1e-9)[:,None]
        out=a-hip;out[:,1]=0;out/=np.maximum(np.linalg.norm(out,axis=1),1e-9)[:,None]
        dr=dir0*(1-g)-up*g
        flat=np.linalg.norm(dr[:,[0,2]],axis=1)<.3
        dr[flat]+=out[flat]*.35*weight
        dr/=np.maximum(np.linalg.norm(dr,axis=1),1e-9)[:,None]
        p=a+dr*L[:,None]
        for _ in range(PASSES):p=_project(p,a,L,thighs,seat)
        if len(shins):
            ax=E-S;fr=np.clip(np.einsum('nci,ci->nc',p[:,None]-S,ax)/np.maximum((ax*ax).sum(1),1e-12),0,1)
            c=S+fr[:,:,None]*ax;rad=p[:,None]-c;dist=np.linalg.norm(rad,axis=2);depth=RS-dist;j=depth.argmax(1);n=np.arange(len(p))
            hit=depth[n,j]>0
            if hit.any():
                p=np.where(hit[:,None],p+rad[n,j]/np.maximum(dist[n,j],1e-9)[:,None]*depth[n,j][:,None],p)
                v=p-a;p=a+v/np.maximum(np.linalg.norm(v,axis=1),1e-9)[:,None]*L[:,None]
        dr=(p-a)/np.maximum(L,1e-9)[:,None]
        # World-space rotation that turns the old segment into the draped one.
        R=_rotations(dir0@flip,dr@flip);R[~ok]=np.eye(3)
        world[nodes,:3,:3]=R@world[nodes,:3,:3]
        local[setup['level_slots'][k]]=np.linalg.solve(world[setup['level_parents'][k]],world[nodes])
        moved+=int(ok.sum())
    _rebuild(world,local,setup)
    springs._drape_cache={'t':started,'w':weight,'local':local[setup['drape_slots']].copy()}
    springs.drape_stats={'ms':round((time.perf_counter()-started)*1000,3),'joints':moved,'weight':round(weight,3),'cached':False}

def _rebuild(world,local,setup,roots=False):
    if roots:world[setup['root_nodes']]=world[setup['root_parents']]@local[setup['root_slots']]
    for nodes,parents,slots in setup['rebuild']:
        world[nodes]=world[parents]@local[slots]

def _rotations(a,b):
    """Batched minimal rotations a->b (unit vectors)."""
    v=np.cross(a,b);c=np.einsum('ij,ij->i',a,b);s2=np.einsum('ij,ij->i',v,v)
    K=np.zeros((len(a),3,3));K[:,0,1]=-v[:,2];K[:,0,2]=v[:,1];K[:,1,0]=v[:,2];K[:,1,2]=-v[:,0];K[:,2,0]=-v[:,1];K[:,2,1]=v[:,0]
    f=np.where(s2>1e-12,(1-c)/np.maximum(s2,1e-12),.5)
    R=np.eye(3)[None]+K+K@K*f[:,None,None]
    R[c<-.9999]=np.eye(3)
    return R
