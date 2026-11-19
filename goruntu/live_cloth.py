"""Local particle cloth using an explicitly authored Houdini topology profile.

This is a local PBD solver, NOT Houdini/Vellum running inside Yumi. Profiles
are exact-hash opt-ins; unknown models retain their existing garment path.
"""
import json,time
from pathlib import Path
import numpy as np

SUPPORTED={'ce8edb9a9be7193fe550cf604b5907f4d066e490a590ab53ed67e6954b42d8fc':'ce8edb9a-a10.json'}

class LiveCloth:
    def __init__(self,model,profile):
        from cloth_constraints import relax
        self.relax=relax
        self.model=model;self.profile=profile;d=model.data
        self.part=profile['part'];p=d.parts[self.part]
        self.ids=np.unique(p['indices']);self.mapping=np.array(profile['source_to_sim'],int)
        self.rest=np.array(profile['rest'],float);self.pins=np.array(profile['pins'],int)
        assert len(self.ids)==len(self.mapping)
        self.first=np.array([np.flatnonzero(self.mapping==i)[0] for i in range(len(self.rest))])
        edges=set();opposites={}
        for a,b,c in profile['triangles']:
            for i,j,k in ((a,b,c),(b,c,a),(c,a,b)):
                edge=tuple(sorted((i,j)));edges.add(edge);opposites.setdefault(edge,[]).append(k)
        bend={tuple(sorted(v)) for v in opposites.values() if len(v)==2 and v[0]!=v[1]}
        self.edges=np.array(sorted(edges),int);self.bends=np.array(sorted(bend),int)
        self.lengths=np.linalg.norm(self.rest[self.edges[:,0]]-self.rest[self.edges[:,1]],axis=1)
        self.blengths=np.linalg.norm(self.rest[self.bends[:,0]]-self.rest[self.bends[:,1]],axis=1)
        self.inv=np.ones(len(self.rest));self.inv[self.pins]=0
        self.pos=None;self.velocity=np.zeros_like(self.rest);self.last=None;self.stats={}
        self.contact_radii=None
        # Nonadjacent particle pairs only; initial authored near-contacts remain.
        a,b=np.triu_indices(len(self.rest),1);dist=np.linalg.norm(self.rest[a]-self.rest[b],axis=1)
        adjacent=np.zeros((len(self.rest),len(self.rest)),bool)
        adjacent[self.edges[:,0],self.edges[:,1]]=True
        keep=(dist>.009)&~adjacent[a,b];self.selfpairs=(a[keep],b[keep])

    def target(self):
        d=self.model.data;p=d.parts[self.part];nodes,inverse=d.skins[p['skin']]
        palette=self.model.world[nodes]@inverse
        skin=np.sum(palette[p['joints'][self.ids]]*p['weights'][self.ids,:,None,None],axis=1)
        raw=np.c_[p['pos'][self.ids],np.ones(len(self.ids))]
        posed=np.einsum('nij,nj->ni',skin,raw)[:,:3]
        target=((posed@d.flip.T-d.origin)*d.scale)[self.first]
        # Waist anchors belong to the pelvis frame, not authored thigh springs.
        # Seated thigh skinning can otherwise pull the belt apart irreconcilably.
        hip=d.bones['hips'];frame=self.model.world[hip]@np.linalg.inv(d.rest[hip])
        rest_source=(self.rest[self.pins]/d.scale+d.origin)@d.flip
        pinned=(np.c_[rest_source,np.ones(len(rest_source))]@frame.T)[:,:3]
        target[self.pins]=(pinned@d.flip.T-d.origin)*d.scale
        return target,skin

    def capsules(self):
        m=self.model;d=m.data;p=m.hair_springs.physics;p.update(m.world)
        names={'pelvis','leftThigh','rightThigh','leftShin','rightShin'}
        ids=[i for i,c in enumerate(p.capsules) if c.name in names]
        starts=(p.starts[ids]@d.flip.T-d.origin)*d.scale
        ends=(p.ends[ids]@d.flip.T-d.origin)*d.scale
        radii=p.radii[ids]*d.scale
        if self.contact_radii is None:
            rs=np.array([(d.rest[p.capsules[i].first,:3,3]@d.flip.T-d.origin)*d.scale for i in ids])
            re=np.array([(d.rest[p.capsules[i].second,:3,3]@d.flip.T-d.origin)*d.scale for i in ids])
            _,length=self.distances(self.rest,rs,re)
            self.contact_radii=np.minimum(radii,length*.98)
        return starts,ends

    @staticmethod
    def distances(pos,a,b):
        axis=b-a;f=np.clip(np.einsum('vci,ci->vc',pos[:,None]-a,axis)/np.maximum(np.sum(axis*axis,axis=1),1e-12),0,1)
        delta=pos[:,None]-a-f[:,:,None]*axis
        return delta,np.linalg.norm(delta,axis=2)

    def contacts(self,a,b):
        delta,length=self.distances(self.pos,a,b);depth=self.contact_radii-length
        which=depth.argmax(1);rows=np.arange(len(self.pos));normal=delta[rows,which]/np.maximum(length[rows,which,None],1e-9)
        self.pos+=normal*np.maximum(depth[rows,which],0)[:,None]*self.inv[:,None]
        pa,pb=self.selfpairs;diff=self.pos[pa]-self.pos[pb];size=np.linalg.norm(diff,axis=1)
        hit=(size<.006)&(size>1e-9)
        if np.any(hit):
            ia=pa[hit];ib=pb[hit];den=np.maximum(self.inv[ia]+self.inv[ib],1)
            corr=diff[hit]*((.006-size[hit])/size[hit]/den)[:,None]
            np.add.at(self.pos,ia,corr*self.inv[ia,None]);np.add.at(self.pos,ib,-corr*self.inv[ib,None])
        env=getattr(self.model.hair_springs.physics,'environment',None)
        if env is not None and not env.scene.desk:
            local=self.pos@env.matrix[:3,:3].T+env.matrix[:3,3]
            top,valid=env.fields[0].sample(local)
            # Only catch downward crossing from above the seat, not a hanging hem.
            old=self.previous@env.matrix[:3,:3].T+env.matrix[:3,3]
            hit=valid&(old[:,1]>=top-.015)&(local[:,1]<top+.006)&(self.inv>0)
            local[hit,1]=top[hit]+.006
            self.pos=local@env.inverse[:3,:3].T+env.inverse[:3,3]

    def step(self,now):
        started=time.perf_counter();target,skin=self.target();a,b=self.capsules()
        elapsed=0 if self.last is None else now-self.last
        if self.pos is None or elapsed<0 or elapsed>.25 or np.max(np.linalg.norm(target[self.pins]-self.pos[self.pins],axis=1))>.35:
            self.pos=target.copy();self.velocity[:]=0;elapsed=0
        self.last=now
        count=min(3,max(0,int(np.ceil(elapsed*60-1e-8))))
        dt=min(elapsed,.05)/max(count,1)
        for _ in range(count):
            self.previous=self.pos.copy()
            self.velocity[:,1]-=9.80665*dt
            self.velocity*=np.exp(-3*dt)
            self.pos+=self.velocity*dt
            self.relax(self.pos,self.inv,self.edges,self.lengths,self.bends,self.blengths,target,self.pins,a,b,self.contact_radii)
            self.contacts(a,b);self.pos[self.pins]=target[self.pins]
            self.velocity=(self.pos-self.previous)/max(dt,1e-8)
            speed=np.linalg.norm(self.velocity,axis=1)
            self.velocity*=np.minimum(1,2/np.maximum(speed,1e-9))[:,None]
        if not np.isfinite(self.pos).all() or np.max(np.linalg.norm(self.pos-target,axis=1))>.65:
            self.pos=target.copy();self.velocity[:]=0
            self.stats['resets']=self.stats.get('resets',0)+1
        d=self.model.data;source=(self.pos[self.mapping]/d.scale+d.origin)@d.flip
        bind=np.linalg.solve(skin,np.c_[source,np.ones(len(source))][...,None])[...,0][:,:3]
        ratio=np.linalg.norm(self.pos[self.edges[:,0]]-self.pos[self.edges[:,1]],axis=1)/np.maximum(self.lengths,1e-9)
        self.stats.update(milliseconds=(time.perf_counter()-started)*1000,max_edge_ratio=float(ratio.max()),pin_error=float(np.max(np.linalg.norm(self.pos[self.pins]-target[self.pins],axis=1))))
        self.stats.update(max_edge_extension=float(np.max((ratio-1)*self.lengths)),p95_edge_ratio=float(np.percentile(ratio,95)),worst_rest_length=float(self.lengths[ratio.argmax()]))
        return {'part':self.part,'ids':self.ids.tolist(),'positions':np.round(bind,6).ravel().tolist()}

def patches(model,now=None):
    key=getattr(model.data,'source_sha256',None)
    if key not in SUPPORTED:return []
    state=getattr(model,'_live_cloth',None)
    # Furniture contact failed dynamic strain acceptance. Retain the existing
    # seating solution for the entire interaction, including approach/exit.
    if getattr(model,'seating',None) is not None:
        if state is not None:
            state.pos=None;state.last=None;state.stats['fallback']='furniture interaction'
        return []
    if getattr(model,'_live_cloth_unavailable',False):return []
    if state is None:
        try:
            profile=json.loads((Path(__file__).resolve().parents[1]/'assets/cloth'/SUPPORTED[key]).read_text(encoding='utf8'))
            if profile['source_sha256']!=key:return []
            state=model._live_cloth=LiveCloth(model,profile)
        except (ImportError,OSError,ValueError,KeyError,AssertionError) as error:
            import logging
            logging.getLogger(__name__).warning('Canli kumas kullanilamiyor: %s',type(error).__name__)
            model._live_cloth_unavailable=True
            return []
    try:
        patch=state.step(time.perf_counter() if now is None else now)
    except (ValueError,ArithmeticError,np.linalg.LinAlgError):
        state.pos=None;state.last=None;state.stats['fallback']='invalid numerical frame'
        return []
    if state.stats['max_edge_ratio']>1.30:
        state.pos=None;state.last=None;state.stats['fallback']='strain limit'
        return []
    state.stats.pop('fallback',None)
    return [patch]
