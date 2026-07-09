"""bench_prediction_materials.py
==============================

Valida el gate de materiales de Prediccion (opcion A: los materiales
DETERMINAN el RT60, por candidato).

  1. effective_rt60 "target" -> devuelve el rt60_target tipeado.
  2. "uniform" -> Sabine hacia adelante; coincide con la formula a mano.
  3. RT60 por candidato: dos geometrias distintas -> RT60 distinto.
  4. Mas absorcion -> menos RT60 (monotono).
  5. "preset" (reflectante: madera/ladrillo/madera) -> RT mayor que alpha=0.31.
  6. El RT60 mueve metricas: verify_candidate_fem con rt distinto -> Schroeder
     distinto (confirma que threadear el rt importa).
  7. End-to-end: predict() corre en modo "uniform" sin reventar.

Uso: python bench_prediction_materials.py
"""

from __future__ import annotations
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from pathlib import Path
import prediction as pr
import material_library as ml

_LIB = ml.MaterialLibrary(str(Path(__file__).resolve().parent / "materials"))


def mk_inputs(**kw):
    base = dict(use="estudio de grabación", program="música", priority=0.5,
                capacity=4, m2_per_person=1.0, rt60_target=0.6,
                v_per_person=10.0)
    base.update(kw)
    return pr.PredictInputs(**base)


def cand(w, l, h):
    return pr.Candidate(ratio_name="t", ratio_note="", width=w, length=l,
                        height=h)


TESTS = []
def test(fn):
    TESTS.append(fn); return fn


@test
def t1_target_mode():
    c = cand(6.0, 8.0, 3.0)
    assert pr.effective_rt60(mk_inputs(), c) == 0.6, "target debe devolver rt60_target"
    return "modo target -> rt60_target (0.6 s)"


@test
def t2_uniform_formula():
    c = cand(6.0, 8.0, 3.0)          # V=144, S=180
    a = 0.31
    rt = pr.effective_rt60(mk_inputs(alpha_mode="uniform", alpha_uniform=a), c)
    expect = 0.161 * 144.0 / (a * 180.0)
    assert abs(rt - expect) < 1e-9, f"{rt} != {expect}"
    return f"uniform alpha=0.31 -> RT60 {rt:.3f} s (Sabine OK)"


@test
def t3_per_candidate():
    inp = mk_inputs(alpha_mode="uniform", alpha_uniform=0.31)
    rt1 = pr.effective_rt60(inp, cand(6.0, 8.0, 3.0))
    rt2 = pr.effective_rt60(inp, cand(4.0, 5.0, 3.0))
    assert abs(rt1 - rt2) > 1e-3, "dos geometrias deberian dar RT distinto"
    return f"RT por candidato: 6x8x3 -> {rt1:.3f} s ; 4x5x3 -> {rt2:.3f} s"


@test
def t4_more_alpha_less_rt():
    c = cand(6.0, 8.0, 3.0)
    rt_lo = pr.effective_rt60(mk_inputs(alpha_mode="uniform", alpha_uniform=0.31), c)
    rt_hi = pr.effective_rt60(mk_inputs(alpha_mode="uniform", alpha_uniform=0.60), c)
    assert rt_hi < rt_lo, "mas absorcion deberia bajar el RT60"
    return f"alpha 0.31 -> {rt_lo:.3f} s  >  alpha 0.60 -> {rt_hi:.3f} s"


def _materials_inputs(preset, **kw):
    mf, mw, mc = ml.preset_surface_materials(_LIB, preset)
    return mk_inputs(alpha_mode="materials",
                     surface_alpha=(mf.alpha_bands(), mw.alpha_bands(),
                                    mc.alpha_bands()), **kw)


@test
def t5_materials_reflective():
    c = cand(6.0, 8.0, 3.0)
    rt = pr.effective_rt60(_materials_inputs("Reflectante / viva"), c)
    rt_u31 = pr.effective_rt60(mk_inputs(alpha_mode="uniform", alpha_uniform=0.31), c)
    assert rt > 0
    assert rt > rt_u31, "el preset reflectante debería dar RT mayor que α=0.31"
    return f"materials 'Reflectante' -> {rt:.2f} s (reflectante, > {rt_u31:.2f})"


@test
def t5b_materials_treated_vs_reflective():
    c = cand(6.0, 8.0, 3.0)
    rt_refl = pr.effective_rt60(_materials_inputs("Reflectante / viva"), c)
    rt_trat = pr.effective_rt60(_materials_inputs("Estudio tratado"), c)
    assert rt_trat < rt_refl, "estudio tratado debería tener RT menor que reflectante"
    return f"estudio tratado {rt_trat:.2f} s < reflectante {rt_refl:.2f} s"


@test
def t5c_preset_resolver():
    mf, mw, mc = ml.preset_surface_materials(_LIB, "Reflectante / viva")
    assert "madera" in mf.name.lower(), mf.name
    assert "ladrillo" in mw.name.lower(), mw.name
    sf, sw, sc = ml.preset_surface_materials(_LIB, "Estudio tratado")
    # panel acustico (estudio) absorbe mas a 500 Hz que el ladrillo (reflectante)
    assert sw.alpha(500) > mw.alpha(500)
    return (f"resolver OK: piso='{mf.name}', paredes='{mw.name}'; "
            f"panel α500={sw.alpha(500):.2f} > ladrillo {mw.alpha(500):.2f}")


@test
def t6_rt_drives_metrics():
    c = cand(6.0, 8.0, 3.0)
    f_lo = pr.verify_candidate_fem(c, rt60_target=0.30)
    f_hi = pr.verify_candidate_fem(c, rt60_target=1.50)
    assert f_lo.schroeder_freq != f_hi.schroeder_freq, (
        "el rt60 deberia mover la frecuencia de Schroeder")
    return (f"Schroeder rt=0.3 -> {f_lo.schroeder_freq:.0f} Hz ; "
            f"rt=1.5 -> {f_hi.schroeder_freq:.0f} Hz")


@test
def t7_end_to_end_uniform():
    inp = mk_inputs(alpha_mode="uniform", alpha_uniform=0.31)
    preds = pr.predict(inp)
    assert preds, "predict() no devolvio candidatos"
    assert all(p.score_total >= 0 for p in preds)
    return f"predict() modo uniform -> {len(preds)} cards, top {preds[0].score_total:.0f}"


def run():
    ok = 0
    for fn in TESTS:
        try:
            msg = fn()
            print(f"  [OK]   {fn.__name__}: {msg}")
            ok += 1
        except Exception as e:
            import traceback
            print(f"  [FAIL] {fn.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{ok}/{len(TESTS)} tests OK")
    return ok == len(TESTS)


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
