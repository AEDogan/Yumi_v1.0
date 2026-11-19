"""Bounded multi-layer triangle columns for local furniture contact proxies.

Unlike a top envelope, paired crossings leave air under a cushion empty.
Open/overflowing columns are unknown and never used as solid evidence.
"""
import numpy as np

class SolidColumns:
    def __init__(self,triangles,axes,size=64,max_hits=48):
        self.axes=axes;self.size=size;u,v,h=axes;t=np.asarray(triangles,float)
        self.minimum=t[:,:,[u,v]].min(axis=(0,1))-.01
        self.extent=t[:,:,[u,v]].max(axis=(0,1))+.01-self.minimum
        hits=np.full((size*size,max_hits),np.inf,dtype=np.float32);counts=np.zeros(size*size,dtype=np.int32)
        # Batched rasterisation: the same per-triangle cell test as a triangle loop,
        # with hit slots assigned in triangle order (identical overflow behaviour).
        if len(t):
            a,b,c=t[:,0],t[:,1],t[:,2]
            du=b[:,u]-a[:,u];dv=b[:,v]-a[:,v];eu=c[:,u]-a[:,u];ev=c[:,v]-a[:,v];det=du*ev-dv*eu
            lo=np.maximum(0,np.floor((t[:,:,[u,v]].min(1)-self.minimum)/self.extent*size-.5).astype(int))
            hi=np.minimum(size-1,np.ceil((t[:,:,[u,v]].max(1)-self.minimum)/self.extent*size-.5).astype(int))
            keep=(np.abs(det)>=1e-10)&np.all(hi>=lo,axis=1)
            tri=np.nonzero(keep)[0];width=hi[tri,0]-lo[tri,0]+1;cells=width*(hi[tri,1]-lo[tri,1]+1)
            owner=np.repeat(tri,cells);start=np.repeat(np.cumsum(cells)-cells,cells)
            k=np.arange(len(owner))-start;w=np.repeat(width,cells)
            xx=lo[owner,0]+k%w;yy=lo[owner,1]+k//w
            ao=a[owner]
            px=self.minimum[0]+(xx+.5)/size*self.extent[0]-ao[:,u];py=self.minimum[1]+(yy+.5)/size*self.extent[1]-ao[:,v]
            d=det[owner];s=(px*ev[owner]-py*eu[owner])/d;r=(du[owner]*py-dv[owner]*px)/d
            inside=(s>=-1e-6)&(r>=-1e-6)&(s+r<=1.000001)
            owner,s,r,ao=owner[inside],s[inside],r[inside],ao[inside]
            ids=yy[inside]*size+xx[inside]
            values=ao[:,h]+s*(b[owner,h]-ao[:,h])+r*(c[owner,h]-ao[:,h])
            order=np.argsort(ids,kind='stable');sorted_ids=ids[order]
            first=np.searchsorted(sorted_ids,sorted_ids,side='left')
            slots=np.empty(len(ids),dtype=np.int64);slots[order]=np.arange(len(ids))-first
            valid=slots<max_hits;hits[ids[valid],slots[valid]]=values[valid]
            counts+=np.bincount(ids,minlength=size*size).astype(np.int32)
        hits.sort(axis=1);finite=np.isfinite(hits)
        # Shared edges and coplanar triangles describe one crossing.
        gaps=np.zeros_like(hits);np.subtract(hits[:,1:],hits[:,:-1],out=gaps[:,1:],where=finite[:,1:]&finite[:,:-1])
        distinct=finite&np.c_[np.ones(len(hits),bool),gaps[:,1:]>1e-4]
        order=np.cumsum(distinct,axis=1)-1;rows,cols=np.nonzero(distinct)
        layers=np.full_like(hits,np.inf);layers[rows,order[rows,cols]]=hits[rows,cols]
        n=distinct.sum(axis=1);self.valid=(counts<max_hits)&(n>=2)&(n%2==0)
        self.layers=layers

    def query(self,points):
        points=np.asarray(points,float);uv=(points[:,list(self.axes[:2])]-self.minimum)/self.extent
        in_bounds=np.all((uv>=0)&(uv<1),axis=1);index=np.clip((uv*self.size).astype(int),0,self.size-1)
        flat=index[:,1]*self.size+index[:,0];layers=self.layers[flat];height=points[:,self.axes[2]]
        below=(layers<height[:,None]).sum(axis=1);valid=in_bounds&self.valid[flat]
        inside=valid&(below%2==1)
        low=layers[np.arange(len(points)),np.maximum(0,below-1)]
        high=layers[np.arange(len(points)),np.minimum(layers.shape[1]-1,below)]
        return valid,inside,low,high

class SolidContacts:
    def __init__(self,triangles,size=64):
        self.columns=[SolidColumns(triangles,axes,size) for axes in ((0,2,1),(0,1,2),(2,1,0))]

    def project(self,points,margin=.006):
        points=np.asarray(points,float);result=points.copy();valids=[];insides=[];distances=[];targets=[]
        for column in self.columns:
            valid,inside,low,high=column.query(points);axis=column.axes[2];value=points[:,axis]
            choose_low=np.abs(value-low)<np.abs(high-value)
            target=np.where(choose_low,low-margin,high+margin)
            valids.append(valid);insides.append(inside)
            distances.append(np.where(inside,np.abs(target-value),np.inf));targets.append(target)
        valid=np.array(valids);inside=np.array(insides)
        # Require agreement of at least two closed cross-sections. A known
        # outside section vetoes a correction instead of filling an open gap.
        solid=(inside.sum(axis=0)>=2)&~np.any(valid&~inside,axis=0)
        best=np.argmin(distances,axis=0)
        for i,column in enumerate(self.columns):
            selected=solid&(best==i);result[selected,column.axes[2]]=targets[i][selected]
        return result
