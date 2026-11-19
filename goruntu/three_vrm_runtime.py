"""Local three-vrm SpringBone bridge; models and user data never leave the PC."""
import atexit,base64,json,logging,os,queue,shutil,subprocess,threading,uuid
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]/'vrm_runtime'
log=logging.getLogger(__name__)

class RuntimeError3D(RuntimeError):pass

class Worker:
    def __init__(self):
        gomulu=Path(__file__).resolve().parents[1]/'runtime'/'node'/'node.exe'  # F1b: kurulumla gelen Node.js
        node=str(gomulu) if gomulu.is_file() else shutil.which('node')
        if not node:raise RuntimeError3D('three-vrm için Node.js çalışma zamanı bulunamadı.')
        if not (ROOT/'node_modules/@pixiv/three-vrm/package.json').is_file():
            raise RuntimeError3D('three-vrm yerel bağımlılıkları kurulmamış.')
        self.process=subprocess.Popen([node,str(ROOT/'spring_worker.mjs')],cwd=ROOT,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            text=True,encoding='utf-8',bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.responses=queue.Queue();self.outbound=queue.Queue(maxsize=1);self.lock=threading.Lock();self.seq=0
        threading.Thread(target=self._read,args=(self.process.stdout,self.responses),daemon=True,name='YumiThreeVRM').start()
        threading.Thread(target=self._write,args=(self.process.stdin,self.outbound,self.responses),daemon=True,name='YumiThreeVRMWrite').start()
    @staticmethod
    def _read(stream,responses):
        try:
            for line in stream:
                try:responses.put(json.loads(line))
                except ValueError:responses.put({'ok':False,'error':'Invalid runtime response'})
        finally:responses.put({'ok':False,'error':'three-vrm runtime stopped'})
    @staticmethod
    def _write(stream,outbound,responses):
        while True:
            line=outbound.get()
            if line is None:return
            try:stream.write(line);stream.flush()
            except (OSError,ValueError):
                responses.put({'ok':False,'error':'three-vrm transport closed'});return
    def request(self,payload,timeout=.25):
        with self.lock:
            if self.process.poll() is not None:raise RuntimeError3D('three-vrm çalışma zamanı kapandı.')
            self.seq+=1;payload={**payload,'seq':self.seq}
            try:
                def _jd(o):
                    if isinstance(o, (np.bool_, bool)):return bool(o)
                    if isinstance(o, (np.floating, float)):return float(o)
                    if isinstance(o, (np.integer, int)):return int(o)
                    if hasattr(o, 'tolist'):return o.tolist()
                    return str(o)
                self.outbound.put_nowait(json.dumps(payload,allow_nan=False,separators=(',',':'),default=_jd)+'\n')
                result=self.responses.get(timeout=timeout)
            except (OSError,queue.Empty,queue.Full) as error:
                self.close();raise RuntimeError3D('three-vrm yanıt vermedi; modelin kaynak pozu korundu.') from error
            if not result.get('ok'):raise RuntimeError3D(result.get('error','three-vrm error'))
            if result.get('seq')!=self.seq:raise RuntimeError3D('three-vrm frame sequence mismatch')
            return result['result']
    def close(self):
        try:self.outbound.put_nowait(None)
        except queue.Full:pass
        if self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=1)
        for pipe in (self.process.stdin,self.process.stdout):
            if pipe:
                try:pipe.close()
                except OSError:pass

_worker=None
def worker():
    global _worker
    if _worker is None or _worker.process.poll() is not None:_worker=Worker()
    return _worker
def shutdown():
    if _worker is not None:_worker.close()
atexit.register(shutdown)

# A19: etek sönümü ve sürükleme kuvveti payı (önceki .90/.15; test için ortam değişkeni)
SKIRT_DRAG=float(os.environ.get('YUMI_ETEK_SONUM','.75'))  # A19 10 Kasım: .90 -> .75 (hafif salınım; ölçüm is_067)
SKIRT_FORCE=float(os.environ.get('YUMI_ETEK_KUVVET','.5'))  # A19: .15 -> .5

class ThreeVRMSprings:
    def __init__(self,data):
        self.data=data;self.id=uuid.uuid4().hex;self.last=None;self.closed=False
        self.worker=worker()
        # Pass source declarations unchanged, not reconstructed guessed physics.
        schema={key:data.g.get(key,default) for key,default in (('nodes',[]),('extensions',{}),('extensionsUsed',[]))}
        result=self.worker.request({'op':'init','id':self.id,'json':schema,'local':np.asarray(data.local).transpose(0,2,1).reshape(-1,16).tolist()},timeout=15)
        self.indices=set(result['indices']);self.version=result['version'];self.declarations=result['declarations']
        # Batched hierarchy: same per-node math as the sequential loops, grouped by depth.
        order=list(data.order);depth={}
        for n in order:
            parent=data.parents.get(n);depth[n]=depth.get(parent,0)+1 if parent is not None else 0
        child=[n for n in order if data.parents.get(n) is not None]
        self._roots=np.array([n for n in order if data.parents.get(n) is None],dtype=np.int64)
        self._child=np.array(child,dtype=np.int64);self._parent=np.array([data.parents[n] for n in child],dtype=np.int64)
        self._levels=[]
        for level in range(1,max(depth.values(),default=0)+1):
            nodes=[n for n in child if depth[n]==level]
            if nodes:self._levels.append((np.array(nodes,dtype=np.int64),np.array([data.parents[n] for n in nodes],dtype=np.int64)))
    def apply(self,t,world,external_velocity=None,hair_nodes=(),cloth_nodes=(),skirt_nodes=()):
        d=self.data;local=world.copy()
        if len(self._child):local[self._child]=np.linalg.solve(world[self._parent],world[self._child])
        dt=1/60 if self.last is None else t-self.last
        reset=self.last is None or dt<0 or dt>.15;self.last=t;self.frame_dt=max(0.,min(dt,.05))
        result=self.worker.request({'op':'step','id':self.id,'dt':max(0.,min(dt,.05)),'reset':reset,
            'skirtNodes':list(skirt_nodes),'skirtDrag':SKIRT_DRAG,'skirtForce':SKIRT_FORCE,'clothNodes':list(cloth_nodes),'hairNodes':list(hair_nodes),'externalForce':(-np.asarray(external_velocity if external_velocity is not None else np.zeros(3))*.04).tolist(),
            'localB64':base64.b64encode(np.ascontiguousarray(local.transpose(0,2,1),dtype='<f8').tobytes()).decode('ascii')})
        from vrm import rotation
        for index,q in result['rotations']:
            # Preserve authored nonuniform scale, not only unit rotation.
            scale=np.linalg.norm(local[index,:3,:3],axis=0)
            if np.linalg.det(local[index,:3,:3])<0:scale[0]*=-1
            local[index,:3,:3]=rotation(q)@np.diag(scale)
        if len(self._roots):world[self._roots]=local[self._roots]
        for nodes,parents in self._levels:world[nodes]=world[parents]@local[nodes]
    def close(self):
        if self.closed:return
        self.closed=True
        if self.worker.process.poll() is None:
            try:self.worker.request({'op':'close','id':self.id})
            except RuntimeError3D:pass
