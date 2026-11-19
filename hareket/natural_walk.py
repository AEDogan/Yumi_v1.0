"""Reference-guided locomotion: support knee extension, low foot lift, relaxed arms."""
import math
from weakref import WeakKeyDictionary
import numpy as np
from motion import ik
from vrm import aim
class NaturalWalkClip:
 def __init__(self,source):self.source=source;self.duration=source.duration;self.neutral=WeakKeyDictionary();self.lifts=WeakKeyDictionary();self.speeds=WeakKeyDictionary();self.baked=WeakKeyDictionary();self.levels=WeakKeyDictionary()
 def _hierarchy(self,target):
  # Depth groups of target.order: same per-node products as a sequential pass.
  if target not in self.levels:
   depth={};roots=[];groups={}
   for i in target.order:
    if i in target.parents:depth[i]=depth.get(target.parents[i],0)+1;groups.setdefault(depth[i],[]).append(i)
    else:depth[i]=0;roots.append(i)
   levels=[(np.array(n,dtype=np.int64),np.array([target.parents[i] for i in n],dtype=np.int64)) for _,n in sorted(groups.items())]
   self.levels[target]=(np.array(roots,dtype=np.int64),levels)
  return self.levels[target]
 def world(self,target,rotations,translation):
  roots,levels=self._hierarchy(target);hips=target.bones['hips']
  local=np.array(target.local,dtype=float)
  for i,m in rotations.items():local[i,:3,:3]=m
  world=np.empty_like(target.rest)
  if hips in target.order and hips not in target.parents:local[hips,:3,3]+=np.linalg.inv(np.eye(4)[:3,:3])@translation
  if len(roots):world[roots]=np.eye(4)@local[roots]
  for nodes,parents in levels:
   if hips in target.parents and hips in target.order and np.any(nodes==hips):
    local[hips,:3,3]+=np.linalg.inv(world[target.parents[hips]][:3,:3])@translation
   world[nodes]=world[parents]@local[nodes]
  return world
 def point(self,target,world,node):return (world[node,:3,3]@target.flip.T-target.origin)*target.scale
 def target_foot(self,target,original,node):
  foot=self.point(target,original,node);rest=self.point(target,target.rest,node);result=foot.copy()
  result[2]=rest[2]+.45*(foot[2]-rest[2]);height=foot[1]-rest[1]
  result[1]=rest[1]+(.60*height if height>0 else height)
  # Keep each foot in its own lane, relative to the moving pelvis.
  # Source retargeting can otherwise pull ankles across the midline.
  hips=self.point(target,original,target.bones['hips'])
  rest_hips=self.point(target,target.rest,target.bones['hips'])
  side='left' if node==target.bones['leftFoot'] else 'right'
  rest_hip=self.point(target,target.rest,target.bones[side+'UpperLeg'])
  offset=rest_hip[0]-rest_hips[0];sign=1. if offset>=0 else -1.
  lane=max(.10,abs(offset)*.90)
  outward=max(0.,sign*(foot[0]-hips[0])-lane)
  result[0]=hips[0]+sign*(lane+min(.035,outward*.25))
  return result
 def geometry(self,target,original):
  legs=[]
  for side in ('left','right'):
   a,b,c=[target.bones[side+p] for p in ('UpperLeg','LowerLeg','Foot')]
   hip,knee,foot=[self.point(target,original,node) for node in (a,b,c)]
   u=knee-hip;v=foot-knee;upper=np.linalg.norm(u);lower=np.linalg.norm(v)
   flex=math.acos(float(np.clip(np.dot(u,v)/upper/lower,-1,1)))
   end=self.target_foot(target,original,c)
   lateral=(end[0]-hip[0])**2+(end[2]-hip[2])**2
   reach=math.sqrt(upper*upper+lower*lower+2*upper*lower*math.cos(min(flex,math.radians(20))))
   required=end[1]+math.sqrt(max(0.,reach*reach-lateral))-hip[1]
   maximum=end[1]+math.sqrt(max(0.,(upper+lower-1e-4)**2-lateral))-hip[1]-.012
   legs.append((a,b,c,hip,end,upper,lower,required,maximum))
  return legs
 def build_cache(self,target):
  key=target;samples=[];raw=[]
  for t in np.linspace(0,self.duration,96,endpoint=False):
   rotations,translation,_=self.source.pose(float(t),target,True);samples.append(rotations)
   legs=self.geometry(target,self.world(target,rotations,translation));heights=[leg[4][1] for leg in legs]
   weights=np.exp(-(np.array(heights)-min(heights))/.04)
   raw.append(max(0.,min(.35,float(np.dot([leg[7] for leg in legs],weights)/sum(weights)))))
  offsets=np.arange(-6,7);weights=np.exp(-.5*(offsets/2.7)**2);weights/=sum(weights)
  self.lifts[key]=sum(np.roll(raw,int(offset))*weight for offset,weight in zip(offsets,weights))
  from motion_reference import reference_pose
  reference_local,_=reference_pose(self.source,target)
  neutral={}
  for side in ('left','right'):
   for part in ('Shoulder','UpperArm','LowerArm','Hand'):
    node=target.bones.get(side+part)
    if node is None or not all(node in frame for frame in samples):continue
    average=sum(frame[node] for frame in samples)/len(samples)
    if part=='LowerArm':average=average*.30+reference_local[node][:3,:3]*.70
    U,_,V=np.linalg.svd(average);neutral[node]=U@np.diag([1,1,np.linalg.det(U@V)])@V
  self.neutral[key]=neutral
 def solve_pose(self,t,target,loop=True):
  rotations,translation,expressions=self.source.pose(t,target,loop);original=self.world(target,rotations,translation)
  key=target
  if key not in self.lifts:self.build_cache(target)
  legs=self.geometry(target,original);phase=(t/self.duration)%1;index=phase*96;i=int(index);u=index-i
  curve=self.lifts[key];lift=curve[i]*(1-u)+curve[(i+1)%96]*u
  lift=max(0.,min(lift,min(leg[8] for leg in legs)))
  translation=translation+target.flip.T@np.array([0.,lift,0.])/target.scale
  desired={}
  for a,b,c,hip,end,upper,lower,_,_ in legs:
   hip=hip+np.array([0.,lift,0.]);direction=end-hip;direction/=max(1e-9,np.linalg.norm(direction))
   rest_hip=self.point(target,target.rest,a);rest_center=self.point(target,target.rest,target.bones['hips'])
   side=1. if rest_hip[0]>=rest_center[0] else -1.
   pole=np.array([side*.18,0.,1.]);pole-=direction*np.dot(pole,direction)
   if np.linalg.norm(pole)<1e-6:pole=np.array([1.,0.,0.])
   knee,ankle=ik(hip,end,upper,lower,pole)
   desired[a]=aim(target.rest[b,:3,3]-target.rest[a,:3,3],target.flip.T@(knee-hip))@target.rest[a,:3,:3]
   desired[b]=aim(target.rest[c,:3,3]-target.rest[b,:3,3],target.flip.T@(ankle-knee))@target.rest[b,:3,:3]
   desired[c]=original[c,:3,:3]
  for node,neutral in self.neutral[key].items():
   weight=.50 if node in (target.bones.get('leftUpperArm'),target.bones.get('rightUpperArm')) else .35
   U,_,V=np.linalg.svd(neutral*(1-weight)+rotations[node]*weight);rotations[node]=U@np.diag([1,1,np.linalg.det(U@V)])@V
  adjusted=np.empty_like(target.rest);result=dict(rotations)
  for i in target.order:
   parent=adjusted[target.parents[i]] if i in target.parents else np.eye(4);local=target.local[i].copy()
   if i in desired:result[i]=np.linalg.inv(parent[:3,:3])@desired[i]
   if i in result:local[:3,:3]=result[i]
   if i==target.bones['hips']:local[:3,3]+=np.linalg.inv(parent[:3,:3])@translation
   adjusted[i]=parent@local
  from relaxed_hands import relaxed_hands
  return relaxed_hands(result,target),translation,expressions


 def prepare(self,target):
  key=target
  if key in self.baked:return
  # M16 (17 Kas): model başına ~3 s'lik pişirme diskte saklanır; anahtar = modelin yürüyüşte kullanılan
  # sayısal girdileri + klip dosyası + hesap kodu. Kayıt yoksa/bozuksa aynı hesap yapılır (sonuç bit bit aynı).
  cached=_disk_load(self,target)
  if cached is not None:self.baked[key]=cached;return
  self._bake(target);_disk_save(self,target,self.baked[key])
 def _bake(self,target):
  key=target
  count=256;frames=[];translations=[]
  for time in np.linspace(0,self.duration,count,endpoint=False):
   r,p,_=self.solve_pose(float(time),target,True);frames.append(r);translations.append(p)
  from joint_limits import limit_rotation,rotation_limits
  limits=rotation_limits(target.bones)
  from motion_reference import reference_pose
  reference_local,_=reference_pose(self.source,target)
  for frame in frames:
   for node in set(frame)&set(limits):frame[node]=limit_rotation(reference_local[node][:3,:3],frame[node],limits[node])
  nodes=sorted(frames[0]);matrices=np.array([[frame[n] for n in nodes] for frame in frames])
  quaternions=np.empty((count,len(nodes),4))
  for i in range(count):
   for j in range(len(nodes)):quaternions[i,j]=matrix_quaternion(matrices[i,j])
  for i in range(1,count):
   signs=np.sum(quaternions[i-1]*quaternions[i],axis=1)<0;quaternions[i,signs]*=-1
  self.baked[key]=(nodes,quaternions,np.array(translations))
 def pose(self,t,target,loop=True):
  self.prepare(target);nodes,qs,positions=self.baked[target]
  u=(t/self.duration)%1 if loop else max(0.,min(1-1e-9,t/self.duration));index=u*len(qs);i=int(index);a=index-i;j=(i+1)%len(qs)
  q0=qs[i];q1=qs[j].copy();q1[np.sum(q0*q1,axis=1)<0]*=-1
  q=q0*(1-a)+q1*a;q/=np.linalg.norm(q,axis=1)[:,None]
  x,y,z,w=q.T;matrices=np.empty((len(nodes),3,3))
  matrices[:,0,0]=1-2*(y*y+z*z);matrices[:,0,1]=2*(x*y-z*w);matrices[:,0,2]=2*(x*z+y*w)
  matrices[:,1,0]=2*(x*y+z*w);matrices[:,1,1]=1-2*(x*x+z*z);matrices[:,1,2]=2*(y*z-x*w)
  matrices[:,2,0]=2*(x*z-y*w);matrices[:,2,1]=2*(y*z+x*w);matrices[:,2,2]=1-2*(x*x+y*y)
  return dict(zip(nodes,matrices)),positions[i]*(1-a)+positions[j]*a,{}
 def travel_speed(self,target):
  key=target
  if key not in self.speeds:
   count=96;dt=self.duration/count;positions=[]
   for t in np.linspace(0,self.duration,count,endpoint=False):
    r,p,_=self.pose(float(t),target,True);w=self.world(target,r,p)
    positions.append([self.point(target,w,target.bones[s+'Foot']) for s in ('left','right')])
   positions=np.array(positions);velocities=(np.roll(positions,-1,axis=0)-positions)/dt;values=[]
   for i in range(count):
    for side in (0,1):
     if positions[i,side,1]<=positions[i,1-side,1]+.025 and velocities[i,side,2]<-.02:
      values.append(-velocities[i,side,2])
   if not values:raise ValueError('Yürüyüş klibinde destek ayağı hızı belirlenemedi.')
   self.speeds[key]=float(np.median(values))*PLAYBACK_RATE
  return self.speeds[key]

PLAYBACK_RATE=.3835
START_PHASE=.5

def load_walk():
 from functools import lru_cache
 return _load_walk()

from functools import lru_cache
@lru_cache(maxsize=1)
def _load_walk():
 from pathlib import Path
 from vrma import MotionClip
 return NaturalWalkClip(MotionClip(Path(__file__).resolve().parents[1]/'motions/Yumi-Walk.vrma'))

_CODE_FILES=('hareket/natural_walk.py','goruntu/vrma.py','hareket/motion_reference.py','hareket/relaxed_hands.py','hareket/joint_limits.py','hareket/motion.py','goruntu/vrm.py')
_CODE_DIGEST=None
def _cache_key(clip,target):
 global _CODE_DIGEST
 import hashlib
 from pathlib import Path
 root=Path(__file__).resolve().parents[1]
 if _CODE_DIGEST is None:
  h=hashlib.sha256()
  for name in _CODE_FILES:h.update(name.encode());h.update((root/name).read_bytes())
  _CODE_DIGEST=h.hexdigest()
 h=hashlib.sha256(b'yumi-walk-bake-1');h.update(_CODE_DIGEST.encode())
 source=getattr(getattr(clip,'source',None),'path',None)
 h.update(Path(source).read_bytes() if source is not None else repr(clip.duration).encode())
 h.update(str(getattr(target,'source_sha256','')).encode());h.update(str(getattr(target,'mapping_sha256','')).encode())
 for array in (np.asarray(target.local,dtype=float),np.asarray(target.rest,dtype=float),np.asarray(target.flip,dtype=float),np.asarray(target.origin,dtype=float),np.asarray([target.scale],dtype=float)):
  h.update(np.ascontiguousarray(array).tobytes())
 h.update(repr((sorted(target.bones.items()),list(target.order),sorted(target.parents.items()),bool(target.legacy))).encode())
 # A27 M18: Witcher anime hareket yolu acikken referans pozu witcher_motion.py'ye baglidir.
 from witcher_motion import active as _witcher_active
 if _witcher_active(target):h.update(b'witcher-motion-1');h.update((root/'hareket'/'witcher_motion.py').read_bytes())
 from app_paths import data_dir  # G-A2: önbellek kullanıcı veri alanında (uygulama klasörüne yazılmaz)
 return h.hexdigest(),data_dir()/'onbellek'/'yuruyus'
def _disk_load(clip,target):
 try:
  digest,folder=_cache_key(clip,target);path=folder/(digest+'.npz')
  if not path.is_file():return None
  with np.load(path,allow_pickle=False) as f:
   nodes=[int(n) for n in f['nodes']];quaternions=np.array(f['quaternions'],dtype=float);translations=np.array(f['translations'],dtype=float)
  if quaternions.shape!=(256,len(nodes),4) or translations.shape[0]!=256:return None
  return nodes,quaternions,translations
 except Exception:return None
def _disk_save(clip,target,baked):
 try:
  import os
  digest,folder=_cache_key(clip,target);folder.mkdir(parents=True,exist_ok=True)
  nodes,quaternions,translations=baked;temporary=folder/(digest+'.%d.tmp.npz'%os.getpid())
  np.savez(temporary,nodes=np.asarray(nodes,dtype=np.int64),quaternions=np.asarray(quaternions,dtype=float),translations=np.asarray(translations,dtype=float))
  os.replace(temporary,folder/(digest+'.npz'))
 except Exception:pass

def matrix_quaternion(m):
 q=np.zeros(4);trace=float(np.trace(m))
 if trace>0:
  s=math.sqrt(trace+1)*2;q[3]=s/4;q[0]=(m[2,1]-m[1,2])/s;q[1]=(m[0,2]-m[2,0])/s;q[2]=(m[1,0]-m[0,1])/s
 else:
  i=int(np.argmax(np.diag(m)));j=(i+1)%3;k=(i+2)%3;s=math.sqrt(max(1e-12,1+m[i,i]-m[j,j]-m[k,k]))*2
  q[i]=s/4;q[3]=(m[k,j]-m[j,k])/s;q[j]=(m[j,i]+m[i,j])/s;q[k]=(m[k,i]+m[i,k])/s
 return q/np.linalg.norm(q)
