"""Exact insertion DP: known sources unordered, pending search sites ordered.

移植说明（absorbed 版）：与源 Q3_Q4_V3\\workstreams\\q4_deep_optimization_v4_20260912\\ordered_tour.py 逐行一致，
仅模块 docstring 补注。`from numba import njit` **保留**（真实算法依赖，见 MANIFEST.md）。
"""
import math
import numpy as np
from numba import njit

@njit(cache=True)
def solve_ordered(position,points,k):
    n=len(points);m=n-k
    locations=np.vstack((points,position.reshape(1,2)))
    D=np.empty((n+1,n+1))
    for i in range(n+1):
        for j in range(n+1):D[i,j]=math.sqrt(((locations[i]-locations[j])**2).sum())
    dp=np.full((m+1,1<<k,k+1),np.inf)
    pred=np.full((m+1,1<<k,k+1),-1,np.int16)
    dp[0,0,k]=0.
    for j in range(m+1):
        for mask in range(1<<k):
            for last in range(k+1):
                value=dp[j,mask,last]
                if not np.isfinite(value):continue
                at=last if last<k else k+j-1 if j>0 else n
                for t in range(k):
                    if mask & (1<<t):continue
                    new=mask|(1<<t);score=value+D[at,t]
                    if score<dp[j,new,t]:dp[j,new,t]=score;pred[j,new,t]=last
                if j<m:
                    score=value+D[at,k+j]
                    if score<dp[j+1,mask,k]:dp[j+1,mask,k]=score;pred[j+1,mask,k]=last
    mask=(1<<k)-1;j=m;last=int(np.argmin(dp[j,mask]));score=dp[j,mask,last]
    order=np.empty(n,np.int16)
    for z in range(n-1,-1,-1):
        before=pred[j,mask,last]
        if last==k:order[z]=k+j-1;j-=1
        else:order[z]=last;mask^=1<<last
        last=before
    return order,score

def ordered_tour(position,points,unordered_count):
    if not len(points):return [],0.
    order,value=solve_ordered(np.asarray(position,dtype=float),np.asarray(points,dtype=float),unordered_count)
    return [int(i) for i in order],float(value)
