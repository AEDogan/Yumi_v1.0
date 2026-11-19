"""Compiled sequential distance constraints; imported only for opted-in cloth."""
import math
from numba import njit

@njit(cache=True)
def relax(pos, inv, edges, lengths, bends, blengths, target, pins, starts, ends, radii):
    for iteration in range(40):
        for kind in range(2):
            if kind==1 and iteration%5:continue
            pairs=edges if kind==0 else bends
            rests=lengths if kind==0 else blengths
            stiffness=1.0 if kind==0 else .08
            for k in range(len(pairs)):
                a,b=pairs[k];dx=pos[a,0]-pos[b,0];dy=pos[a,1]-pos[b,1];dz=pos[a,2]-pos[b,2]
                length=math.sqrt(dx*dx+dy*dy+dz*dz);mass=inv[a]+inv[b]
                if length<1e-10 or mass==0:continue
                factor=(length-rests[k])/length/mass*stiffness
                for axis in range(3):
                    delta=(pos[a,axis]-pos[b,axis])*factor
                    pos[a,axis]-=delta*inv[a];pos[b,axis]+=delta*inv[b]
        if iteration%5==4:
            for i in range(len(pos)):
                if inv[i]==0:continue
                for j in range(len(starts)):
                    axis=ends[j]-starts[j];offset=pos[i]-starts[j]
                    square=axis[0]**2+axis[1]**2+axis[2]**2
                    f=max(0.,min(1.,(offset[0]*axis[0]+offset[1]*axis[1]+offset[2]*axis[2])/max(square,1e-12)))
                    delta=offset-axis*f
                    size=math.sqrt(delta[0]**2+delta[1]**2+delta[2]**2)
                    if size<radii[i,j] and size>1e-9:
                        pos[i]+=delta*((radii[i,j]-size)/size)
        for i in pins:pos[i]=target[i]
