"""A31 ikinci tur (17 Kas): kose duzeyinde oturma dokumu - kalcadan asili Witcher etegi (Shani-Dugun).
Neden: eklem (yay zinciri) dokumu etegi sert bir tepsi gibi dondurur -> yana/koltuk disina yayiliyor, ic etek/bacak
ustten deliyordu (kullanici, 17 Kas). Burada her etek kosesi ayakta durus bicimindeki yerinden (bel bandindan
asagi kumas uzunlugu s, bel cevresindeki acisi) oturmus bedene YENIDEN dokulur:
  bel bandi kalcayla gider; kumas yercekimiyle duser, destek yuzeyine (bacak + ic etek + minder) konunca o yonde ilerler
  (on: uyluk boyunca, dizden sonra sarkar), minder ustunde kumas yigilir (yatay ilerleme kisaltilir, yana yayilmaz),
  koltuk kolu / yuksek duvara tirmanmaz, desteksiz yerde dikey sarkar.
Shani-Dugun'da uyluga deri ile bagli bant da dis etegin parcasi (bacagin etekten cikma nedeni) -> butun parca dokulur;
destek = bacak/kalca govdesi + uyluk/baldir kapsulleri + iki uyluk arasi hamak + minder. Kenar gerilmesi PBD ile <=1,1x.
Yalniz Witcher + MODELS listesi; YUMI_OTUR_ETEK=0 kapatir. Hedef kalca cercevesinde saklanir: oturmusken diz kalcaya gore 3 cm (3 sn sonra 1,2 cm) oynarsa yeniden cozulur (~13-18 ms); aradaki karelerde yalniz donusum. Ilk oturusta kurulum+koltuk alani ~80-150 ms (bir kez).
"""
import os,time
from pathlib import Path
import numpy as np

# G-A2 (18 Kas): model listesi koddan cikti -> karakter.json gorunumler[].davranis.otur_etek_dokum (yalniz Witcher paketi)
MARGIN=.045;STEP=.018;BUNCH=.35;WALL=.05;CELL=.02

def enabled(model):
    if os.environ.get('YUMI_OTUR_ETEK','1')=='0':return False
    from seat_rig import witcher_package
    import karakterler
    return witcher_package(model) and bool(karakterler.davranis(model,'otur_etek_dokum',False))

def _can(d,P):return (P@d.flip.T-d.origin)*d.scale

def _skin(d,part,ids,W):
    nodes,inverse=d.skins[part['skin']]
    s=np.sum((W[nodes]@inverse)[part['joints'][ids]]*part['weights'][ids,:,None,None],axis=1)
    return s,_can(d,np.einsum('nij,nj->ni',s,np.c_[part['pos'][ids],np.ones(len(ids))])[:,:3])

def _bone(d,W):
    h=d.bones['hips'];R=d.flip@W[h,:3,:3]@d.flip.T;U,_,V=np.linalg.svd(R);return U@V,_can(d,W[h,:3,3])

def _hip(d,W):
    """Kalca cercevesi BEDEN eksenlerinde (dinlenmede kimlik: kanonik +z on, +y yukari); kemik eksenleri modele gore donuk."""
    R,h=_bone(d,W);R0,_=_bone(d,d.rest);return R@R0.T,h

def setup(model):
    if '_a31_skirt' in model.__dict__:return model.__dict__['_a31_skirt']
    from seated_garment import panels
    d=model.data;hs=model.hair_springs;human=set(d.bones.values())
    flex=set(hs.cloth_nodes)|set(hs.skirt_nodes)
    legroots={d.bones[s+k] for s in ('left','right') for k in ('UpperLeg','LowerLeg','Foot')};leg=set(legroots)
    for n in range(len(d.nodes)):
        a=n
        while a in d.parents and a not in human:a=d.parents[a]
        if a in legroots and n not in flex:leg.add(n)
    R0,h0=_hip(d,d.rest);drape=[];support=[]
    for ordinal,part,ids,*_ in panels(model):
        nodes,_=d.skins[part['skin']];bm=np.sum(part['weights'][ids]*np.isin(nodes[part['joints'][ids]],list(leg)),1)
        free=ids;tight=ids[:0]  # Shani-Dugun: uyluga deri ile bagli bant da dis etegin parcasi (bacak icinden cikma nedeni) -> hepsi dokulur
        if len(tight):support.append((part,tight))
        if not len(free):continue
        _,P=_skin(d,part,free,d.rest);L=(P-h0)@R0
        drape.append({'part':ordinal,'ids':free,'local':L})
    if not drape:model.__dict__['_a31_skirt']=None;return None
    L=np.concatenate([x['local'] for x in drape]);th=np.arctan2(L[:,0],L[:,2])
    # dikis kaynagi (ayni konumdaki kopya koseler) + kumas yuzeyi boyunca bel bandina uzaklik (jeodezik)
    _,weld=np.unique(np.round(L/2e-4).astype(np.int64),axis=0,return_inverse=True);weld=weld.ravel()
    tri=[];offset=0
    for x in drape:
        part=d.parts[x['part']];slot=-np.ones(len(part['pos']),int);slot[x['ids']]=np.arange(len(x['ids']))+offset
        t=slot[part['indices'].reshape(-1,3)];tri.append(t[(t>=0).all(1)]);offset+=len(x['ids'])
    tri=np.concatenate(tri);E=np.concatenate([tri[:,[0,1]],tri[:,[1,2]],tri[:,[2,0]]]);E=np.unique(np.sort(weld[E],1),axis=0);E=E[E[:,0]!=E[:,1]]
    nw=weld.max()+1;Lw=np.zeros((nw,3));Lw[weld]=L;length=np.linalg.norm(Lw[E[:,0]]-Lw[E[:,1]],axis=1)
    # bel bandi kaynaklari: 24 aci diliminde dilimin en ust 3 cm'i, yalniz kalca seviyesine yakin olanlar
    # (on acikligin alt eteginden olusan dilimler kaynak olmaz; bel cizgisi onde V yapabilir)
    top=Lw[:,1].max();tw=np.arctan2(Lw[:,0],Lw[:,2]);bw=((tw+np.pi)/(2*np.pi)*24).astype(int)%24;seed=np.zeros(nw,bool)
    for k in range(24):
        m=bw==k
        if m.any():seed|=m&(Lw[:,1]>Lw[m,1].max()-.03)&(Lw[:,1]>-.20)
    dist=np.where(seed,0.,np.inf);src=np.arange(nw)
    for _ in range(400):
        changed=False
        for a,b in ((0,1),(1,0)):
            cand=dist[E[:,a]]+length;better=cand<dist[E[:,b]]
            if better.any():
                order=np.argsort(-cand[better]);i=E[better,b][order];dist[i]=cand[better][order];src[i]=src[E[better,a]][order];changed=True
        if not changed:break
    lost=~np.isfinite(dist)  # bel bandina bagli olmayan ada: dikey uzaklik, kendi acisinda
    dist[lost]=np.maximum(0,top-Lw[lost,1]);src[lost]=np.flatnonzero(lost)
    s=dist[weld];anchor=Lw[src[weld]].copy()
    anchor[lost[weld],1]=top
    start=anchor
    # destek: bacak govde parcalari (kumas/sac/yuz disi), seyreltilmis
    for part in d.parts:
        if part.get('skin') is None or 'joints' not in part or part['kind'] in ('cloth','hair','face'):continue
        nodes,_=d.skins[part['skin']];used=np.unique(part['indices'])
        bm=np.sum(part['weights'][used]*np.isin(nodes[part['joints'][used]],list(leg)),1)
        _,Pr=_skin(d,part,used,d.rest);Pr-=h0
        # bacak + uyluk koku/kalca (kalca seviyesinin altinda, kollar haric): kasik/uyluk kokunde kumas govdeye gomulmesin
        arm={d.bones.get(k) for k in ('leftUpperArm','rightUpperArm','leftLowerArm','rightLowerArm','leftHand','rightHand')}-{None}
        am=np.sum(part['weights'][used]*np.isin(nodes[part['joints'][used]],list(arm)),1)
        sel=used[((bm>.3)|(Pr[:,1]<.02))&(am<.2)][::2]
        if len(sel):support.append((part,sel))
    edges=E  # dikis kaynakli komsuluk (yumusatma)
    ph=hs.physics;caps=[i for i,c in enumerate(ph.capsules) if c.name in ('leftThigh','rightThigh','leftShin','rightShin')]
    result={'rest_len':length,'drape':drape,'theta':th,'s':s,'start':start,'support':support,'edges':edges,'caps':caps,'cache':None,'weld':weld}
    model.__dict__['_a31_skirt']=result;return result

def _fields(environment):
    f=getattr(environment,'_a31_skirt_fields',None)
    if f is None:
        from furniture_scene import rotation
        from furniture_contacts import SurfaceField
        from seated_garment import seat_level_field
        sc=environment.scene;fit=sc.fit
        tri=np.concatenate([((p['pos']-fit.pivot)@rotation(-fit.yaw).T*fit.scale)[p['indices'].reshape(-1,3)] for p in sc.asset.parts])
        f=environment._a31_skirt_fields=(seat_level_field(environment),SurfaceField(tri,(0,2,1),size=64))
    return f

def _solve(model,setup,W):
    d=model.data;env=model.hair_springs.physics.environment;R,h=_hip(d,W)
    up=np.array([0.,1.,0.]);fw=R@np.array([0,0,1.]);fw[1]=0;fw/=np.linalg.norm(fw);lat=np.cross(up,fw)
    # destek noktalari (kanonik), kalca merkezli yatay izgara (u=yan, v=ileri)
    pts=[_skin(d,part,ids,W)[1] for part,ids in setup['support']]
    ph=model.hair_springs.physics;ph.update(W)
    for i in setup['caps']:
        A=_can(d,ph.starts[i]);Bc=_can(d,ph.ends[i]);r=ph.radii[i]*d.scale
        t=np.linspace(0,1,24)[:,None];ax=A+(Bc-A)*t
        a=np.linspace(0,2*np.pi,12,endpoint=False);u_=np.cross(Bc-A,up);u_/=max(np.linalg.norm(u_),1e-9);w_=np.cross(u_,(Bc-A)/max(np.linalg.norm(Bc-A),1e-9))
        ring=(np.cos(a)[:,None]*u_+np.sin(a)[:,None]*w_)*r
        pts.append((ax[:,None,:]+ring[None]).reshape(-1,3))
    P=np.concatenate(pts)-h;U=P@lat;V=P@fw
    nu,nv=64,72;u0,v0=-.64,-.56
    H=np.full((nu,nv),-np.inf);iu=((U-u0)/CELL).astype(int);iv=((V-v0)/CELL).astype(int);ok=(iu>=0)&(iu<nu)&(iv>=0)&(iv<nv)
    np.maximum.at(H,(iu[ok],iv[ok]),P[ok,1]+h[1])  # mutlak kanonik y (minder ile ayni)
    # delik doldur: 3x3 en buyuk
    G=H.copy()
    for du in (-1,0,1):
        for dv in (-1,0,1):G=np.maximum(G,np.roll(np.roll(H,du,0),dv,1))
    # iki uyluk arasi hamak: ayni ileri sirada iki yaninda bacak destegi olan bos hucre, alcak olanin 3 cm altinda
    sup=np.isfinite(G);idx=np.arange(nu)[:,None]*np.ones((1,nv),int)
    lv=np.where(sup,G,-np.inf);li=np.where(sup,idx,-10**6);rv=lv.copy();ri=np.where(sup,idx,10**6)
    for i in range(1,nu):
        take=~sup[i]&np.isfinite(lv[i-1]);lv[i]=np.where(take,lv[i-1],lv[i]);li[i]=np.where(take,li[i-1],li[i])
    for i in range(nu-2,-1,-1):
        take=~sup[i]&np.isfinite(rv[i+1]);rv[i]=np.where(take,rv[i+1],rv[i]);ri[i]=np.where(take,ri[i+1],ri[i])
    gap=~sup&np.isfinite(lv)&np.isfinite(rv)&((ri-li)*CELL<.30)
    G=np.where(gap,np.minimum(lv,rv)-.03,G)
    legcell=np.isfinite(G)
    # yuzey puruzunu gider: bacak hucrelerinde 3x3 ortalama (yalniz destekli komsular), sonra en buyukle birlestir
    Gf=np.where(legcell,G,0.);n=legcell.astype(float);acc=np.zeros_like(Gf);cn=np.zeros_like(Gf)
    for du in (-1,0,1):
        for dv in (-1,0,1):acc+=np.roll(np.roll(Gf,du,0),dv,1);cn+=np.roll(np.roll(n,du,0),dv,1)
    G=np.where(legcell,np.maximum(G,acc/np.maximum(cn,1)),G)
    # minder + koltuk zarfi (koltuk yerel cerceve)
    gu,gv=np.meshgrid(u0+(np.arange(nu)+.5)*CELL,v0+(np.arange(nv)+.5)*CELL,indexing='ij')
    Q=h+gu[...,None]*lat+gv[...,None]*fw;M=env.matrix;loc=Q.reshape(-1,3)@M[:3,:3].T+M[:3,3]
    seat,whole=_fields(env);top,valid=seat.sample(loc);allt,allv=whole.sample(loc)
    fit=env.scene.fit;inside=valid&(np.abs(loc[:,0])<fit.width*.5+.02)
    cushion=np.where(inside,top-M[1,3],-np.inf)  # kanonik y (M yalniz donme+oteleme, y ekseni korunur)
    wall=(allv&(allt>top+WALL)&inside)|(allv&~valid&(allt>fit.height+WALL))
    cushion=cushion.reshape(nu,nv);wall=wall.reshape(nu,nv)
    S=np.maximum(G,cushion)
    def surf(p):
        q=p-h;a=np.clip(((q@lat-u0)/CELL).astype(int),0,nu-1);b=np.clip(((q@fw-v0)/CELL).astype(int),0,nv-1)
        return S[a,b]+MARGIN,legcell[a,b],wall[a,b]
    th=setup['theta'];st=setup['start'];rem=setup['s'].copy()
    # baslangic: bel bandi noktasi (kalca cercevesinde ayakta yeri)
    pos=st@R.T+h
    dirn=lat[None]*(np.sin(th)*np.where(np.cos(th)>0,.55,1.))[:,None]+fw[None]*np.cos(th)[:,None]
    dirn/=np.maximum(np.linalg.norm(dirn,axis=1),1e-9)[:,None];moving=np.ones(len(pos),bool)
    # bel bandi oturunca uyluk kokunun icinde kalabilir: baslangic destegin ustune alinir (kumas uyluktan gecmez)
    h0_,_,_=surf(pos);pos[:,1]=np.maximum(pos[:,1],h0_)
    for _ in range(140):
        act=rem>1e-5
        if not act.any():break
        hcur,_,_=surf(pos);gap=pos[:,1]-hcur
        fall=act&(gap>1e-4);dy=np.minimum(np.minimum(gap,STEP),rem);pos[fall,1]-=dy[fall];rem[fall]-=dy[fall]
        walk=act&~fall&moving
        if walk.any():
            stepv=np.minimum(STEP,rem);nxt=pos+dirn*stepv[:,None];hn,lg,wl=surf(nxt)
            blocked=wl|(hn-pos[:,1]>WALL)
            factor=np.where(lg,1.,BUNCH)
            nxt=pos+dirn*(stepv*factor)[:,None];hn2,_,_=surf(nxt)
            climb=np.maximum(0,hn2-pos[:,1]);go=walk&~blocked
            pos[go]=nxt[go];pos[go,1]=np.maximum(pos[go,1],hn2[go]);rem[go]-=np.where(lg,stepv,np.hypot(stepv,climb))[go]  # bacak ustunde kumas kayar: yalniz yatay boy
            stop=walk&blocked;moving[stop]=False;rem[stop]=0
        stuck=act&~fall&~moving;rem[stuck]=0
    # yumusatma (komsu ortalamasi, 2 gecis) ve destegin ustunde tut
    e=setup['edges'];weld=setup['weld'];nw=weld.max()+1
    cnt=np.bincount(weld,minlength=nw).astype(float);pw=np.zeros((nw,3));np.add.at(pw,weld,pos);pw/=cnt[:,None]
    for _ in range(3):
        if not len(e):break
        acc=np.zeros_like(pw);c=np.zeros(nw)
        np.add.at(acc,e[:,0],pw[e[:,1]]);np.add.at(acc,e[:,1],pw[e[:,0]]);np.add.at(c,e[:,0],1);np.add.at(c,e[:,1],1)
        has=c>0;pw[has]=pw[has]*.5+acc[has]/c[has,None]*.5
        hcur,_,_=surf(pw);pw[:,1]=np.maximum(pw[:,1],hcur)
    # gerilme siniri (PBD): kenar dinlenme boyunun 1,1 katini asmaz (yigilma serbest); her geciste destegin ustune
    if len(e):
        rest=setup['rest_len']
        for _ in range(30):
            dv=pw[e[:,1]]-pw[e[:,0]];ln=np.linalg.norm(dv,axis=1);over=ln>rest*1.1
            if not over.any():break
            corr=(dv*((ln-rest*1.1)/np.maximum(ln,1e-9))[:,None]*.5)*over[:,None]
            acc=np.zeros_like(pw);c=np.zeros(nw);np.add.at(acc,e[:,0],corr);np.add.at(acc,e[:,1],-corr);np.add.at(c,e[:,0],over);np.add.at(c,e[:,1],over)
            pw+=acc/np.maximum(c,1)[:,None];hcur,_,_=surf(pw);pw[:,1]=np.maximum(pw[:,1],hcur)
    return (pw[weld]-h)@R

def patches(model):
    """(yamalar, kapsanan parca kumesi). Oturmuyorsa ya da kapaliysa ([], set())."""
    seating=model.seating;weight=float(seating.weight) if seating is not None else 0.
    if weight<=.001 or not enabled(model):
        if '_a31_skirt' in model.__dict__ and model.__dict__['_a31_skirt']:model.__dict__['_a31_skirt']['cache']=None
        return [],set()
    env=getattr(model.hair_springs.physics,'environment',None)
    if env is None or env.scene.desk:return [],set()
    st=setup(model)
    if st is None:return [],set()
    d=model.data;W=model.world;now=time.perf_counter();R,h=_hip(d,W)
    knees=np.concatenate([(_can(d,W[d.bones[s+'LowerLeg'],:3,3])-h)@R for s in ('left','right')])
    c=st['cache']
    moved=np.abs(knees-c['k']).max() if c is not None else 1.
    if c is None or (weight<.999 and now-c['t']>.2) or (weight>.999 and (c['w']<.999 or (now-c['t']>.5 and moved>.03) or (now-c['t']>3 and moved>.012))):
        t0=time.perf_counter();local=_solve(model,st,W)
        st['cache']=c={'t':now,'k':knees,'w':weight,'local':local,'ms':(time.perf_counter()-t0)*1000}
    target=c['local']@R.T+h;amount=weight*weight*(3-2*weight);out=[];k=0;owned=set()
    for x in st['drape']:
        part=d.parts[x['part']];ids=x['ids'];n=len(ids)
        skin,posed=_skin(d,part,ids,W);corr=posed+(target[k:k+n]-posed)*amount;k+=n
        source=(corr/d.scale+d.origin)@d.flip
        bind=np.linalg.solve(skin,np.c_[source,np.ones(n)][...,None])[...,0][:,:3]
        out.append({'part':int(x['part']),'ids':ids.tolist(),'positions':np.round(bind,6).ravel().tolist()});owned.add(int(x['part']))
    return out,owned
