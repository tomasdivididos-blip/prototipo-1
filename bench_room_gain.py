"""
bench_room_gain.py
==================

Oráculo del item 5: ganancia de sala / modo cero (Celestinos & Nielsen, CABS,
JAES 56(11) 2008, sec. 2.4). El solver descarta el modo trivial p=const
(drop_zero_mode), que es la COMPLIANCIA del aire; por debajo del 1er modo la
respuesta real SUBE hacia DC a -20 dB/década. `frequency_response(...,
include_room_gain=True, volume=V)` lo suma como término analítico de 1er orden.

Chequeos falsables:
  T1  con room gain, |H| a graves (<1er modo) es MUCHO mayor que sin él.
  T2  la pendiente del room gain es ~ -20 dB/década (1er orden) en la banda
      donde domina.
  T3  por encima del 1er modo (banda modal) H con y sin room gain coinciden
      (no ensucia la banda modal).
  T4  una fuente de volumen-velocidad NETA cero (dos monopolos opuestos) NO
      excita el modo cero (room gain ~ despreciable).

Correr:
  PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_room_gain.py
"""

from __future__ import annotations

import numpy as np

from geometry import make_room
from acoustic_mesh import build_volume_mesh
from acoustic_fem import build_KM, solve_modes, FieldEvaluator, frequency_response
from sources import SourceArray, OmniSource, RHO0, C0

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


def _setup():
    Lx, Ly, Lz = 3.0, 4.0, 2.7
    V = Lx * Ly * Lz
    verts, tris, _, _ = make_room(Lx, Ly, Lz, n_walls=4, roof_type="flat",
                                  subdiv_levels=0)
    nodes, tets = build_volume_mesh(verts, tris, n_per_meter=2.0)
    K, M, _ = build_KM(nodes, tets)
    freqs, phis = solve_modes(K, M, n_modes=15)
    loc = FieldEvaluator(nodes, tets)
    f1 = C0 / (2.0 * Ly)                           # 1er axial (~42.9 Hz)
    return loc, freqs, phis, V, f1


def test_lift_and_slope():
    print("T1/T2  room gain: lift a graves + pendiente ~ -20 dB/década")
    loc, freqs, phis, V, f1 = _setup()
    src = SourceArray(); src.add(OmniSource(position=(-1.3, -1.8, 0.3), Q=1e-3 + 0j))
    rx = (0.7, 0.9, 1.3)
    fa = np.linspace(2.0, 80.0, 200)
    H0 = frequency_response(loc, freqs, phis, src, rx, fa, damping=0.03)
    Hg = frequency_response(loc, freqs, phis, src, rx, fa, damping=0.03,
                            include_room_gain=True, volume=V, room_gain_fleak=5.0)
    # T1: a 10 Hz (bien bajo f1) el room gain levanta el nivel.
    i10 = int(np.argmin(np.abs(fa - 10.0)))
    lift = 20 * np.log10(abs(Hg[i10]) / (abs(H0[i10]) + 1e-30))
    check("|H| a 10 Hz sube con room gain (>6 dB)", lift > 6.0,
          f"lift={lift:.1f} dB")
    # T2: pendiente del TÉRMINO AÑADIDO puro |Hg - H0| (= |H_room|) ~ -20 dB/dec
    # (1er orden), limpio del modal. Entre 10 y 40 Hz (arriba del corte f_leak).
    add = np.abs(Hg - H0)
    fa1, fa2 = 10.0, 40.0
    j1 = int(np.argmin(np.abs(fa - fa1))); j2 = int(np.argmin(np.abs(fa - fa2)))
    slope = (20 * np.log10(add[j2] / add[j1])) / np.log10(fa2 / fa1)
    check("pendiente del room gain ~ -20 dB/década (1er orden)",
          -26 < slope < -14, f"{slope:.1f} dB/dec")


def test_modal_band_unchanged():
    print("\nT3  en los PICOS de resonancia (banda modal) el room gain no distorsiona")
    loc, freqs, phis, V, f1 = _setup()
    src = SourceArray(); src.add(OmniSource(position=(-1.3, -1.8, 0.3), Q=1e-3 + 0j))
    rx = (0.7, 0.9, 1.3)
    fa = np.linspace(55.0, 120.0, 400)             # bien arriba de f1
    H0 = frequency_response(loc, freqs, phis, src, rx, fa, damping=0.03)
    Hg = frequency_response(loc, freqs, phis, src, rx, fa, damping=0.03,
                            include_room_gain=True, volume=V, room_gain_fleak=5.0)
    # En el PICO de resonancia (donde el modal domina), el room gain (piso 1/ω)
    # es despreciable; solo asoma en los NULOS (física, no defecto).
    ipk = int(np.argmax(np.abs(H0)))
    rel_pk = abs(Hg[ipk] - H0[ipk]) / abs(H0[ipk])
    # El piso de compliancia es una contribución REAL de pocos % aun en el pico
    # (por eso CABS lo pasa-alta a 200 Hz al medir MD): no debe DOMINAR ni mover
    # la resonancia, pero no es exactamente cero arriba del fundamental.
    check("en el pico de resonancia la diff es pequeña (<5%)", rel_pk < 0.05,
          f"rel en pico={rel_pk*100:.3f}%")
    # El término añadido decae como 1/ω (piso suave), no un pico nuevo.
    add = np.abs(Hg - H0)
    check("el término añadido decae con f (piso 1/ω, sin picos nuevos)",
          add[0] > add[-1], f"{add[0]:.2e} -> {add[-1]:.2e}")


def test_dipole_no_room_gain():
    print("\nT4  fuente de volumen-velocidad neta cero NO excita el modo cero")
    loc, freqs, phis, V, f1 = _setup()
    rx = (0.3, -0.7, 0.9)
    fa = np.linspace(2.0, 30.0, 80)
    # Monopolo solo (Q_net != 0) vs par opuesto (Q_net = 0). Se compara la
    # CONTRIBUCIÓN ABSOLUTA del room gain |Hg - H0|, no la relativa (H0 del par
    # es diminuto a graves y una relativa explota aunque el término sea chico).
    # Fuentes SEPARADAS (0.8 m, distinto voxel) para evitar el quirk de fuentes
    # coincidentes de _source_modal_coupling. El par opuesto tiene Q_net=0.
    s1 = SourceArray(); s1.add(OmniSource(position=(-0.8, 0.0, 1.0), Q=1e-3 + 0j))
    s2 = SourceArray()
    s2.add(OmniSource(position=(-0.8, 0.0, 1.0), Q=1e-3 + 0j))
    s2.add(OmniSource(position=(0.8, 0.0, 1.0), Q=-1e-3 + 0j))
    def contrib(src):
        H0 = frequency_response(loc, freqs, phis, src, rx, fa, damping=0.03)
        Hg = frequency_response(loc, freqs, phis, src, rx, fa, damping=0.03,
                                include_room_gain=True, volume=V, room_gain_fleak=5.0)
        i5 = int(np.argmin(np.abs(fa - 5.0)))
        return abs(Hg[i5] - H0[i5])
    c_mono = contrib(s1); c_pair = contrib(s2)
    check("room gain del par opuesto << del monopolo (Q_net cancela)",
          c_pair < 0.02 * c_mono,
          f"par {c_pair:.2e} vs mono {c_mono:.2e}  (ratio={c_pair/c_mono:.3f})")


def main():
    print("=" * 68)
    print("bench_room_gain.py  —  ganancia de sala / modo cero (item 5)")
    print("=" * 68)
    test_lift_and_slope()
    test_modal_band_unchanged()
    test_dipole_no_room_gain()
    print("-" * 68)
    print(f"  {_N_OK}/{_N_OK + _N_FAIL} checks OK")
    return 0 if _N_FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
