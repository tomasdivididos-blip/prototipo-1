"""bench_geometric_r4.py - R4 del motor geometrico: entradas fisicas de la fuente,
scattering, aire y mixing time (el `bench_source_air_scatter` del plan).

Cada oraculo es una ley cerrada o una referencia tabulada INDEPENDIENTE (no es
modelo-vs-modelo del propio motor):

  O1  DIRECTIVIDAD ANALITICA vs INTEGRAL DE RAYLEIGH: el patron del piston en
      bafle `PistonDirectivity` (D=2J1(ka sinθ)/(ka sinθ)) iguala a la integral
      de Rayleigh NUMERICA sobre el disco (primeros principios), para varios
      angulos y frecuencias; D(0)=1 exacto. Kinsler, Fundamentals of Acoustics
      cap. 7; Beranek, Acustica.
  O2  AIRE ISO 9613-1 vs KUTTRUFF TABLA 6.1: 2*alpha_aire(f) (intensidad) iguala
      a los valores tabulados de m a 20°C (Kuttruff, Room Acoustics 5a ed, Tabla
      6.1), tabulacion independiente del formalismo -> acuerdo <2%.
  O3  SCATTERING, LIMITES: s=0 -> todas las reflexiones ESPECULARES (ISM puro,
      diffuse_frac=0); s=1 -> todas DIFUSAS (Lambert puro, diffuse_frac=1);
      s intermedio -> fraccion difusa ~ s. El default de ingenieria crece con f
      y queda en [0,1].
  O4  MIXING TIME, REGLA DE VOLUMEN: t_mix ~ sqrt(V) (duplicar V -> x sqrt(2));
      a t_mix la densidad temporal de reflexiones (Kuttruff ec. 4.6) vale n_crit;
      y reflection_density = d/dt del conteo acumulado de imagenes (4/3)pi c^3 t^3/V
      (cruce rate<->cumulative, primeros principios).
  O5  CABLEADO DE DIRECTIVIDAD: en early_reflections el directo con el eje
      APUNTANDO al receptor = omni (D(0)=1); perpendicular < on-axis; hacia
      ATRAS ~0 (bafle). diffuse_tail con directividad CONSERVA la potencia total.

Correr:  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_geometric_r4.py
"""
import numpy as np

import geometry
import acoustic_mesh
import acoustic_analysis as aa
import geometric_engine as ge

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


# =========================================================================
print("O1: directividad del piston (analitica) vs integral de Rayleigh")


def rayleigh_piston(a, f, theta, c=343.0, nr=500, nph=900):
    """|p(theta)|/|p(0)| de un piston circular en bafle por integral de Rayleigh
    NUMERICA: suma de fuentes puntuales sobre el disco (primeros principios)."""
    k = 2.0 * np.pi * f / c
    r = (np.arange(nr) + 0.5) / nr * a
    ph = (np.arange(nph) + 0.5) / nph * 2.0 * np.pi
    R, PH = np.meshgrid(r, ph, indexing="ij")
    dA = (a / nr) * (2.0 * np.pi / nph) * R                  # elemento de area
    x = R * np.sin(theta) * np.cos(PH)                       # proyeccion a la direccion
    integ = np.sum(np.exp(1j * k * x) * dA)
    # por la simetria del disco la integral es real; su SIGNO = flip de fase de
    # los lobulos laterales (igual que D=2J1/x signado, no |.|).
    return float(integ.real / np.sum(dA))


a_piston = 0.1
pist = ge.PistonDirectivity(a=a_piston, axis=(0.0, 0.0, 1.0))
errs = []
for f in (2000.0, 4000.0, 8000.0):
    for thdeg in (15.0, 30.0, 45.0, 60.0):
        th = np.radians(thdeg)
        d = np.array([np.sin(th), 0.0, np.cos(th)])
        g = float(pist.gain(d[None, :], [f])[0, 0])
        gr = rayleigh_piston(a_piston, f, th)
        errs.append(abs(g - gr))
on_axis = float(pist.gain(np.array([[0.0, 0.0, 1.0]]), [8000.0])[0, 0])
check("O1 piston = Rayleigh numerico (max err<1e-2) y D(0)=1",
      max(errs) < 1e-2 and abs(on_axis - 1.0) < 1e-12,
      f"max|D_ana - D_rayleigh|={max(errs):.2e}, D(0)={on_axis:.6f}")

# =========================================================================
print("O2: absorcion del aire ISO 9613-1 vs Kuttruff Tabla 6.1 (20°C)")
f_k = np.array([500.0, 1000.0, 2000.0, 3000.0, 4000.0, 6000.0, 8000.0])
# Kuttruff, Room Acoustics 5a ed, Tabla 6.1 (m en 1e-3 m^-1, 20°C, RH=40%):
kut40 = np.array([0.60, 1.07, 2.58, 5.03, 8.40, 17.71, 30.00])
m_iso = 2.0 * aa.air_absorption_alpha(f_k, T=20.0, RH=40.0, P=101325.0) * 1e3
rel = np.max(np.abs(m_iso - kut40) / kut40)
check("O2 2*alpha_aire(f) == Tabla 6.1 (RH=40%, <2%)",
      rel < 0.02,
      f"max rel={rel*100:.2f}%  ISO={np.round(m_iso,2)} vs Kut={kut40}")

# =========================================================================
print("O3: scattering, limites s=0 (ISM) y s=1 (Lambert)")
Lx, Ly, Lz = 5.0, 4.0, 3.0
v, t, *_ = geometry.make_room(Lx, Ly, Lz, n_walls=4)
nodes, tets = acoustic_mesh.build_volume_mesh(v, t, n_per_meter=2.5)
vmin, vmax = nodes.min(0), nodes.max(0)
src = ge.GeoSource(pos=vmin + np.array([0.43, 0.57, 0.50]) * (vmax - vmin))


def frac(s):
    sc = ge.Scene.from_tet_mesh(nodes, tets, alpha=0.1, scatter=s)
    r = ge.diffuse_tail(sc, src, n_rays=2000, dt=0.01, t_max=0.3, max_refl=30,
                        e_min=1e-10, bands=[1000.0], air=False, seed=7)
    return r["diffuse_frac"]


# nota: _resolve_face_spec clipea s a [0, 0.999] (evita sqrt(1-a)=0), por eso
# s=1 -> 0.999 (practicamente todo difuso).
f0, f1, fm = frac(0.0), frac(1.0), frac(0.3)
dflt = ge.default_scattering(ge._ism.octave_bands())
mono = np.all(np.diff(dflt) >= -1e-9)
check("O3 s=0->especular (0.0), s=1->difuso (>0.99), s=0.3->~0.3; default en [0,1] creciente",
      f0 == 0.0 and f1 > 0.99 and abs(fm - 0.3) < 0.05
      and dflt.min() >= 0.0 and dflt.max() <= 1.0 and mono,
      f"frac(s=0)={f0:.3f}, frac(1)={f1:.3f}, frac(0.3)={fm:.3f}; "
      f"default [{dflt.min():.2f},{dflt.max():.2f}] mono={mono}")

# =========================================================================
print("O4: mixing time regla de volumen + densidad de reflexiones")
c = 343.0
V1 = 100.0
t_mix = ge.mixing_time(V1, c=c, n_crit=1000.0)
t_mix2 = ge.mixing_time(2.0 * V1, c=c, n_crit=1000.0)
scaling = t_mix2 / t_mix
# a t_mix la densidad vale n_crit
dens_at = ge.reflection_density(V1, t_mix, c=c)
# rate == d/dt del acumulado de imagenes N(t)=(4/3)pi c^3 t^3 / V (primeros ppios)
tt = 0.05
dtt = 1e-4
cum = lambda tx: (4.0 / 3.0) * np.pi * c ** 3 * tx ** 3 / V1
num_rate = (cum(tt + dtt) - cum(tt - dtt)) / (2 * dtt)
ana_rate = ge.reflection_density(V1, tt, c=c)
check("O4 t_mix~sqrt(V) (x sqrt2), dens(t_mix)=n_crit, rate=d/dt(acumulado)",
      abs(scaling - np.sqrt(2.0)) < 1e-9 and abs(dens_at - 1000.0) < 1e-6
      and abs(num_rate - ana_rate) / ana_rate < 1e-4,
      f"t_mix(V)={t_mix*1e3:.1f} ms, scaling={scaling:.4f} (sqrt2={np.sqrt(2):.4f}); "
      f"dens(t_mix)={dens_at:.1f}/s; rate num={num_rate:.1f} vs ana={ana_rate:.1f}")

# =========================================================================
print("O5: cableado de directividad en early/diffuse")
rec = ge.GeoReceiver(pos=vmin + np.array([0.80, 0.30, 0.50]) * (vmax - vmin))
axis_to = (rec.pos - src.pos) / np.linalg.norm(rec.pos - src.pos)
scn = ge.Scene.from_tet_mesh(nodes, tets, alpha=0.15)

r_omni = ge.early_reflections(scn, src, rec, max_order=1)
src_to = ge.GeoSource(pos=src.pos, directivity=ge.PistonDirectivity(a=0.15, axis=axis_to))
src_perp = ge.GeoSource(pos=src.pos,
                        directivity=ge.PistonDirectivity(a=0.15, axis=np.cross(axis_to, [0, 0, 1])))
src_away = ge.GeoSource(pos=src.pos, directivity=ge.PistonDirectivity(a=0.15, axis=-axis_to))
e_omni = r_omni["direct"]["energy"][-1]
e_to = ge.early_reflections(scn, src_to, rec, max_order=1)["direct"]["energy"][-1]
e_perp = ge.early_reflections(scn, src_perp, rec, max_order=1)["direct"]["energy"][-1]
e_away = ge.early_reflections(scn, src_away, rec, max_order=1)["direct"]["energy"][-1]
check("O5a directo: eje->receptor = omni (D(0)=1); perp < on-axis; atras ~0",
      abs(e_to - e_omni) / e_omni < 1e-9 and e_away < 1e-6 * e_omni
      and 0.0 <= e_perp < e_omni,
      f"e_to/e_omni={e_to/e_omni:.6f}, e_perp/e_omni={e_perp/e_omni:.3e}, "
      f"e_away/e_omni={e_away/e_omni:.3e}")

# potencia total EMITIDA: con alpha=0, aire off y SOLO el primer rebote, la
# energia depositada = potencia emitida = q, independiente de la directividad
# (la renormalizacion conserva q, solo redistribuye su direccion). W por rebote
# completo depende del nº de reflexiones (geometria), por eso se mide a 1er rebote.
scn0 = ge.Scene.from_tet_mesh(nodes, tets, alpha=0.0)
src_d = ge.GeoSource(pos=src.pos, directivity=ge.PistonDirectivity(a=0.2, axis=axis_to))
w1_omni = ge.diffuse_tail(scn0, src, n_rays=4000, dt=0.01, t_max=0.3, max_refl=1,
                          e_min=1e-14, bands=[1000.0], air=False, seed=3)["w"].sum()
w1_dir = ge.diffuse_tail(scn0, src_d, n_rays=4000, dt=0.01, t_max=0.3, max_refl=1,
                         e_min=1e-14, bands=[1000.0], air=False, seed=3)["w"].sum()
check("O5b potencia emitida = q con y sin directividad (1er rebote, ±2%)",
      abs(w1_omni - 1.0) < 0.02 and abs(w1_dir - 1.0) < 0.02,
      f"W1(omni)={w1_omni:.4f}, W1(dir)={w1_dir:.4f} (q=1)")

# =========================================================================
print("O6: BalloonDirectivity (globo medido) recupera un piston muestreado")
# muestrear el piston analitico en una grilla esferica -> construir el globo ->
# consultarlo FUERA de la grilla: debe recuperar el piston (camino del globo
# medido real, p.ej. un export CLF/GLL decodificado).
a_b = 0.12
pst = ge.PistonDirectivity(a=a_b, axis=(0.0, 0.0, 1.0))
th_g = np.radians(np.arange(0.0, 181.0, 5.0))        # 5° (resolucion CF2)
ph_g = np.radians(np.arange(0.0, 360.0, 30.0))       # piston axisimetrico
fr_g = np.array([1000.0, 2000.0, 4000.0, 8000.0])
gdb = np.zeros((len(th_g), len(ph_g), len(fr_g)))
for i, th in enumerate(th_g):
    d = np.array([np.sin(th), 0.0, np.cos(th)])
    glin = np.abs(pst.gain(d[None, :], fr_g)[0])     # |D| del globo (dB rel eje)
    gdb[i, :, :] = 20.0 * np.log10(np.maximum(glin, 1e-6))[None, :]
bal = ge.BalloonDirectivity(theta=th_g, phi=ph_g, freqs=fr_g, gain_db=gdb,
                            axis=(0.0, 0.0, 1.0), ref=(1.0, 0.0, 0.0))
# consulta a una FRECUENCIA de grilla (2000 Hz; interp en f exacta) y ANGULOS
# fuera de la grilla, sobre el lobulo principal (nulo a ~60° a 2000 Hz) -> aisla
# la interpolacion ANGULAR 5°. (A f entre octavas el nulo se mueve y el muestreo
# de octava no lo captura: por eso los globos reales van en 1/3 de octava.)
err_b = []
for thd in (13.0, 22.0, 33.0, 43.0):
    th = np.radians(thd)
    d = np.array([np.sin(th), 0.0, np.cos(th)])
    gb = bal.gain(d[None, :], [2000.0])[0, 0]
    ga = abs(pst.gain(d[None, :], [2000.0])[0, 0])
    err_b.append(abs(gb - ga))
check("O6 BalloonDirectivity recupera |D| del piston fuera de la grilla angular (<2e-2)",
      max(err_b) < 2e-2,
      f"max|balloon - |piston||={max(err_b):.2e} (interp angular 5°, f de grilla)")

n_ok = sum(1 for _n, c in results if c)
print(f"\n{n_ok}/{len(results)} tests OK")
if n_ok < len(results):
    raise SystemExit(1)
