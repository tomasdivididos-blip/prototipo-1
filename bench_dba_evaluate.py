"""
bench_dba_evaluate.py
=====================

Oraculos de `dba_evaluate.evaluate_cabs` (evaluacion CABS de una config de fuentes
real). Estilo del proyecto: asserts falsables, cada uno con su racional fisico.

Correr:
    PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_dba_evaluate.py
"""

from __future__ import annotations

import numpy as np

import dba as _dba
import dba_evaluate as dev
from sources import OmniSource, C0
from sbir import Wall


DIMS = (7.8, 4.1, 2.8)
AXIS = 1                                  # Y (largo)
RX = (3.9, 2.05, 1.4)                     # receptor central (coords caja)
FMAX = 120.0
_n = 0
_ok = 0


def check(name, cond, detail=""):
    global _n, _ok
    _n += 1
    status = "OK " if cond else "FAIL"
    if cond:
        _ok += 1
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail else ""))
    return cond


def _sources_from_specs(specs, stype="subwoofer"):
    srcs = []
    for sp in specs:
        srcs.append(OmniSource(sp["pos"], Q=sp["Q"], label=sp["label"],
                               source_type=stype, delay_s=sp["delay_s"],
                               polarity=sp["polarity"], response=sp["response"]))
    return srcs


def box_walls(dims, R=0.7):
    """6 paredes del paralelepipedo como planos infinitos (coords caja)."""
    Lx, Ly, Lz = dims
    return [
        Wall(point=[0, 0, 0], normal=[1, 0, 0], label="X min", R=R),
        Wall(point=[Lx, 0, 0], normal=[1, 0, 0], label="X max", R=R),
        Wall(point=[0, 0, 0], normal=[0, 1, 0], label="Y min", R=R),
        Wall(point=[0, Ly, 0], normal=[0, 1, 0], label="Y max", R=R),
        Wall(point=[0, 0, 0], normal=[0, 0, 1], label="Z min", R=R),
        Wall(point=[0, 0, Lz], normal=[0, 0, 1], label="Z max", R=R),
    ]


# ---------------------------------------------------------------------------
def test_continuity():
    """T1: el ideal (LS, mismo pipeline) NO puede ser peor que una config naive
    del mismo tamaño. Valida que real e ideal se miden con la misma metrica y que
    la optimizacion LS mejora (o iguala) al retardo naive."""
    print("T1 consistencia (ideal LS no peor que naive)")
    specs = _dba.build_dba_sources(DIMS, axis=AXIS, n_x=3, n_z=3, drive="naive",
                                   fmax=FMAX)
    srcs = _sources_from_specs(specs)
    r = dev.evaluate_cabs(srcs, DIMS, RX, axis=AXIS, fmax=FMAX)
    check("planitud ideal <= real (LS mejora o iguala al naive)",
          r["flat_ideal"] <= r["flat_real"] + 0.5,
          f"real={r['flat_real']:.2f} ideal={r['flat_ideal']:.2f}")
    check("decay ideal <= real + margen (LS colapsa al menos igual)",
          r["decay_ideal"] <= r["decay_real"] + 0.020,
          f"real={r['decay_real']*1e3:.0f}ms ideal={r['decay_ideal']*1e3:.0f}ms")
    check("checklist critico PASA para un DBA naive valido", r["passed"])


def test_discrimination():
    """T2: configs invalidas deben FALLAR el checklist critico; una valida PASA."""
    print("T2 discriminacion (no debe pasar cualquier cosa)")
    # (a) solo array frontal (sin trasero) -> falla "opposing".
    specs = _dba.build_dba_sources(DIMS, axis=AXIS, n_x=2, n_z=2, drive="naive",
                                   fmax=FMAX)
    front_only = [s for s in _sources_from_specs(specs)
                  if s.label.startswith("DBA-F")]
    r_front = dev.evaluate_cabs(front_only, DIMS, RX, axis=AXIS, fmax=FMAX)
    check("solo-front FALLA (sin array enfrentado)", not r_front["passed"])
    opp = [it for it in r_front["checklist"] if it["key"] == "opposing"][0]
    check("checklist marca 'opposing' en FALLA", not opp["ok"])

    # (b) par estereo generico (fullrange en dos esquinas frontales) -> no son
    # subs, no forman array -> FALLA.
    stereo = [OmniSource((1.0, 0.3, 1.2), label="L", source_type="fullrange"),
              OmniSource((6.8, 0.3, 1.2), label="R", source_type="fullrange")]
    r_st = dev.evaluate_cabs(stereo, DIMS, RX, axis=AXIS, fmax=FMAX)
    check("estereo fullrange FALLA (no hay subs enfrentados)", not r_st["passed"])

    # (c) DBA naive valido -> opposing + drive OK.
    good = _sources_from_specs(specs)
    r_good = dev.evaluate_cabs(good, DIMS, RX, axis=AXIS, fmax=FMAX)
    opp_g = [it for it in r_good["checklist"] if it["key"] == "opposing"][0]
    drv_g = [it for it in r_good["checklist"] if it["key"] == "rear_drive"][0]
    check("DBA naive: 'opposing' OK", opp_g["ok"])
    check("DBA naive: 'rear_drive' OK (retardo L/c + inversion)", drv_g["ok"])

    # (d) trasero SIN inversion ni retardo -> drive FALLA.
    bad_drive = _sources_from_specs(specs)
    for s in bad_drive:
        if s.label.startswith("DBA-R"):
            s.delay_s = 0.0
            s.polarity = 1
    r_bad = dev.evaluate_cabs(bad_drive, DIMS, RX, axis=AXIS, fmax=FMAX)
    drv_b = [it for it in r_bad["checklist"] if it["key"] == "rear_drive"][0]
    check("trasero mal manejado: 'rear_drive' FALLA", not drv_b["ok"])


def test_total_response():
    """T3: el criterio usa SBIR + modos. Con paredes (SBIR activo) el resultado
    NO debe ser igual que sin paredes (solo modal) -> ambas contribuciones entran."""
    print("T3 respuesta total = SBIR + modos")
    specs = _dba.build_dba_sources(DIMS, axis=AXIS, n_x=2, n_z=2, drive="naive",
                                   fmax=FMAX)
    srcs = _sources_from_specs(specs)
    # f_S forzado en banda (60 Hz) para que el SBIR entre en [60, 120]; por debajo
    # de f_S el hibrido usa la modal (que ya incluye las reflexiones -> no doble
    # conteo), asi que el SBIR solo cambia el resultado arriba de f_S.
    r_modal = dev.evaluate_cabs(srcs, DIMS, RX, axis=AXIS, fmax=FMAX, walls=None,
                                f_schroeder=60.0)
    r_total = dev.evaluate_cabs(srcs, DIMS, RX, axis=AXIS, fmax=FMAX,
                                walls=box_walls(DIMS), f_schroeder=60.0)
    d_flat = abs(r_total["flat_real"] - r_modal["flat_real"])
    d_sp = abs(r_total["spatial_real"] - r_modal["spatial_real"])
    check("SBIR cambia la planitud vs solo-modal (>0.1 dB)", d_flat > 0.1,
          f"Δflat={d_flat:.2f} dB")
    check("SBIR cambia la varianza espacial vs solo-modal (>0.05 dB)",
          d_sp > 0.05, f"Δspatial={d_sp:.2f} dB")


def test_valid_band():
    """T4: con pocos subs (espaciado grande) la banda valida se acota a
    f_max=c/d < fmax y el checklist lo dice."""
    print("T4 banda valida (aliasing espacial)")
    specs = _dba.build_dba_sources(DIMS, axis=AXIS, n_x=2, n_z=2, drive="naive",
                                   fmax=FMAX)
    srcs = _sources_from_specs(specs)
    r = dev.evaluate_cabs(srcs, DIMS, RX, axis=AXIS, fmax=FMAX)
    check("band_hi < fmax (array esparso -> aliasing)",
          r["band_hi"] < FMAX and np.isfinite(r["f_max"]),
          f"band_hi={r['band_hi']:.0f} Hz  f_max={r['f_max']:.0f} Hz")
    sp = [it for it in r["checklist"] if it["key"] == "spacing"][0]
    check("checklist 'spacing' reporta f_max", "f_max" in sp["text"])


if __name__ == "__main__":
    print("=" * 64)
    print("bench_dba_evaluate.py  —  evaluacion CABS de config real")
    print("=" * 64)
    test_continuity()
    test_discrimination()
    test_total_response()
    test_valid_band()
    print("-" * 64)
    print(f"  {_ok}/{_n} checks OK")
    if _ok != _n:
        raise SystemExit(1)
