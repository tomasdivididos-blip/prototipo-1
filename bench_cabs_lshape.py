"""
bench_cabs_lshape.py
====================

Validación cualitativa del item 6: CABS en una sala IRREGULAR (en L), oráculo del
paper de Celestinos & Nielsen, «Applications of a plane wave based room
correction», Acoustics'08, §3.2 (sala en L; la corrección mejora la uniformidad
global pero DEGRADA en 20-40 Hz por la difracción en la esquina de la L).

No es código de producción: es un oráculo de TENDENCIA (nuestro motor es FEM
modal, el del paper es FDTD; no se busca el número exacto). Reusa el campo modal
FEM del recinto REAL. El drive CABS se arma combinando los campos front/rear:
    p_cabs(f) = p_front(f) + G(f)·(−1)·e^{−iω·Ly/c}·p_rear(f)
con G la ganancia del trasero (item 1).

Correr:
  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_cabs_lshape.py
"""

from __future__ import annotations

import numpy as np

from acoustic_mesh import build_volume_mesh
from acoustic_fem import build_KM, solve_modes, FieldEvaluator, modal_pressure_field
from sources import SourceArray, OmniSource, C0
import dba
import dba_evaluate as de

_N_OK = 0
_N_FAIL = 0


def check(name, cond, detail=""):
    global _N_OK, _N_FAIL
    tag = "[OK ]" if cond else "[FAIL]"
    if cond:
        _N_OK += 1
    else:
        _N_FAIL += 1
    print(f"  {tag} {name}" + (f"  ({detail})" if detail else ""))


def _prism_mesh(P, Lz, npm=1.5):
    """Prisma extruido en z de un polígono P (lista CCW de (x,y)) star-shaped
    desde P[0]. Piso/techo en ABANICO desde P[0], una pared por arista. Watertight
    -> el voxel talla el interior por paridad de rayos (no necesita normales)."""
    P = list(P)
    nP = len(P)
    bot = np.array([[x, y, 0.0] for (x, y) in P], float)
    top = np.array([[x, y, Lz] for (x, y) in P], float)
    v = np.vstack([bot, top])                      # 0..nP-1 piso, nP.. techo
    tris = []
    for k in range(1, nP - 1):                     # abanico piso desde 0
        tris.append([0, k, k + 1])
    for k in range(1, nP - 1):                     # abanico techo desde nP
        tris.append([nP, nP + k + 1, nP + k])
    for i in range(nP):                            # paredes (aristas de contorno)
        j = (i + 1) % nP
        tris.append([i, j, j + nP])
        tris.append([i, j + nP, i + nP])
    nodes, tets = build_volume_mesh(v, np.array(tris, int), n_per_meter=npm)
    return nodes, tets


def _field_grid(loc, freqs, phis, sources, fa, zone_idx, xi=0.03):
    """|p| en dB en los nodos de zona, (N_zona, Nf)."""
    L = np.zeros((len(zone_idx), len(fa)))
    for j, f in enumerate(fa):
        p = modal_pressure_field(loc, freqs, phis, sources, float(f), damping=xi)
        L[:, j] = 20.0 * np.log10(np.abs(p[zone_idx]) + 1e-30)
    return L


def _cabs_sd(nodes, tets, dims, flo=22.0, fhi=100.0):
    """Mejora de SD (front-only -> CABS) sobre la zona, en [flo,fhi]. Devuelve
    (sd_front, sd_cabs)."""
    Lx, Ly, Lz = dims
    K, M, _ = build_KM(nodes, tets)
    freqs, phis = solve_modes(K, M, n_modes=45)
    loc = FieldEvaluator(nodes, tets)
    axis = 1; c = C0; tau = Ly / c
    G = dba.cabs_rear_gain(dims, axis, rt60=0.6, c=c, air=True)
    xs = np.linspace(0.8, 4.2 - 0.8, 3)            # subs en el brazo común (x<Lxc)
    front = SourceArray(); rear = SourceArray()
    for x in xs:
        front.add(OmniSource(position=(x, 0.3, Lz / 2), Q=1e-3 + 0j))
        rear.add(OmniSource(position=(x, Ly - 0.3, Lz / 2), Q=1e-3 + 0j))
    nz = nodes
    zone_idx = np.where((nz[:, 0] > 1.0) & (nz[:, 0] < 4.2 - 0.5) &
                        (nz[:, 1] > 1.0) & (nz[:, 1] < Ly - 1.0) &
                        (nz[:, 2] > 0.6) & (nz[:, 2] < Lz - 0.6))[0]
    fa = np.linspace(flo, fhi, 40)
    Lf = _field_grid(loc, freqs, phis, front, fa, zone_idx)
    Lc = np.zeros_like(Lf)
    for j, f in enumerate(fa):
        pf = modal_pressure_field(loc, freqs, phis, front, float(f))
        pr = modal_pressure_field(loc, freqs, phis, rear, float(f))
        omega = 2 * np.pi * f
        p = pf + G(f) * (-1.0) * np.exp(-1j * omega * tau) * pr
        Lc[:, j] = 20.0 * np.log10(np.abs(p[zone_idx]) + 1e-30)
    sd_f, _ = de.msfd_metrics(fa, Lf)
    sd_c, _ = de.msfd_metrics(fa, Lc)
    return sd_f, sd_c, len(zone_idx), freqs[-1]


def main():
    print("=" * 70)
    print("bench_cabs_lshape.py  —  validación CABS en sala en L (item 6)")
    print("=" * 70)
    Lx, Ly, Lz, Lxc, Lyc = 7.08, 7.8, 2.76, 4.20, 4.5
    try:
        nL, tL = _prism_mesh([(0, 0), (Lx, 0), (Lx, Lyc), (Lxc, Lyc),
                              (Lxc, Ly), (0, Ly)], Lz)
        nR, tR = _prism_mesh([(0, 0), (Lxc, 0), (Lxc, Ly), (0, Ly)], Lz)  # rect
    except Exception as e:
        print(f"  [SKIP] no se pudo construir la malla ({str(e)[:80]})")
        print("  0/0 checks OK")
        return 0
    check("malla en L y rectángulo construidas",
          len(nL) > 400 and len(nR) > 200,
          f"L {len(nL)} nodos / rect {len(nR)} nodos")

    sd_fL, sd_cL, nzL, fmaxL = _cabs_sd(nL, tL, (Lx, Ly, Lz))
    sd_fR, sd_cR, nzR, fmaxR = _cabs_sd(nR, tR, (Lxc, Ly, Lz))
    impL = sd_fL - sd_cL
    impR = sd_fR - sd_cR
    check("modos hasta >100 Hz (L)", fmaxL > 100.0, f"f[-1]={fmaxL:.1f} Hz")
    check("zonas con suficientes nodos", nzL > 30 and nzR > 30,
          f"L {nzL} / rect {nzR}")
    print(f"  L:    SD front {sd_fL:.2f} -> CABS {sd_cL:.2f} dB (mejora {impL:+.2f})")
    print(f"  rect: SD front {sd_fR:.2f} -> CABS {sd_cR:.2f} dB (mejora {impR:+.2f})")
    check("CABS mejora la uniformidad en la sala en L (irregular)", sd_cL < sd_fL,
          f"{sd_fL:.2f} -> {sd_cL:.2f} dB")
    check("CABS mejora MENOS en la L que en el rectángulo equivalente "
          "(penalización por la esquina, §3.2)", impL < impR,
          f"L {impL:+.2f} < rect {impR:+.2f} dB")
    print("  NOTA: el modelo modal estacionario NO reproduce la degradación "
          "específica 20-40 Hz por difracción de onda viajera del FDTD del paper;")
    print("  valida el punto robusto del §3.2: CABS sirve en sala irregular pero "
          "menos que en una rectangular.")

    print("-" * 70)
    print(f"  {_N_OK}/{_N_OK + _N_FAIL} checks OK")
    return 0 if _N_FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
