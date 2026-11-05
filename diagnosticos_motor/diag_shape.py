"""El sesgo del EDT crece con la NO COMPACIDAD de la sala (varianza del camino
libre), no con la absorcion. V y alpha fijos, paredes LISAS (sin voxel), barrido
de forma de cubo a chata. Si EDT/Ey sube con S/V, el mecanismo queda fijado."""
import numpy as np
import geometry, acoustic_mesh
import geometric_engine as ge

ALPHA = 0.24
def eyring_T(V, S, a, c): return 24.0*V*np.log(10.0)/(c*S*(-np.log(1.0-a)))
def sabine_T(V, S, a, c): return 24.0*V*np.log(10.0)/(c*S*a)

def edt_t30(w, dt):
    edc = np.cumsum(w[::-1])[::-1]; edc = edc/max(edc[0],1e-30)
    L = 10.0*np.log10(np.maximum(edc,1e-12)); t = np.arange(len(L))*dt
    def fit(lo,hi):
        s=(L<=lo)&(L>=hi)
        return (-60.0/np.polyfit(t[s],L[s],1)[0]) if s.sum()>=3 else np.nan
    return fit(0.0,-10.0), fit(-5.0,-35.0)

dims = [(3.915,3.915,3.915), (5,4,3), (6,5,2), (8,5,1.5), (10,6,1.0)]
print(f"{'LxLyLz':>14} {'V':>5} {'S':>6} {'S/V':>5} {'4V/S':>5} {'Eyr':>6} | "
      f"{'EDT/Ey':>7} {'T30/Ey':>7} {'mfp':>5}")
for (Lx,Ly,Lz) in dims:
    v,t,*_ = geometry.make_room(Lx,Ly,Lz,n_walls=4)
    nodes,tets = acoustic_mesh.build_volume_mesh(v,t,n_per_meter=2.5)
    vmin,vmax = nodes.min(0),nodes.max(0); ext=vmax-vmin
    src = ge.GeoSource(pos=vmin+np.array([0.43,0.57,0.5])*ext)
    sc = ge.Scene.from_tet_mesh(nodes,tets,alpha=ALPHA)
    V=sc.volume; S=sc.total_area(); c=sc.c
    Tey=eyring_T(V,S,ALPHA,c)
    r = ge.diffuse_tail(sc,src,n_rays=24000,dt=0.002,t_max=2.0,
                        max_refl=1500,e_min=1e-15,bands=[1000.0],air=False,seed=7)
    edt,t30 = edt_t30(r["w"][0], r["dt"])
    print(f"{Lx:4.1f}x{Ly:3.1f}x{Lz:3.1f} {V:5.0f} {S:6.1f} {S/V:5.2f} {4*V/S:5.2f} "
          f"{Tey:6.3f} | {edt/Tey:7.3f} {t30/Tey:7.3f} {r['mean_free_path']:5.2f}")
