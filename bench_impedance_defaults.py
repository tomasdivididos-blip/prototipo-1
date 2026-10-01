"""
bench_impedance_defaults.py - link material -> impedancia por default (feature 1-2)
===================================================================================
Valida `impedance_defaults` bajo el contrato de la ETAPA 2 (1 Oct 2026, decisión
del usuario "elegir qué modelo le toca a cada α"): el TIPO lo elige la FORMA del α
(+ keyword como prior) y los PARAMS se AJUSTAN para que el amortiguamiento del
modelo (Re β a θ=0) reproduzca el del catálogo; si ningún modelo lo logra, o el α
es plano, cae a β real (α exacto). Esto reemplaza el contrato viejo (keyword →
params leídos del nombre), que metía modelos cuyo α contradecía el catálogo y
disparaba un f_Schroeder falso (ver bug-material-no-resuelto-rigido / diagnóstico
Control Ale.room).

Secciones:
  P  parsers (espesor/densidad/cámara) — sin cambios.
  N  caminos SIN modelo (usuario / audiencia / duro / inespecífico) — sin cambios.
  R  recuperación por ORÁCULO: α generado de un modelo conocido -> el clasificador
     recupera el TIPO y el modelo reproduce el α (damping-match).
  S  selección por FORMA del α (rising->poroso, low_peak->membrana aun con keyword
     poroso, plano->β real).
  D  INVARIANTE anti-bug: el Re(β) efectivo (modelo o β real) reproduce el del
     catálogo en graves -> el amortiguamiento NUNCA colapsa (incl. 4 materiales
     reales del profesor).

Correr:  PYTHONIOENCODING=utf-8 python bench_impedance_defaults.py
"""
from __future__ import annotations
import numpy as np

import impedance as imp
import impedance_defaults as idf
import face_materials as fm

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


_OCT = (63, 125, 250, 500, 1000, 2000, 4000, 8000)
_HARD = {63: 0.02, 125: 0.02, 250: 0.03, 500: 0.03,
         1000: 0.04, 2000: 0.05, 4000: 0.05, 8000: 0.06}
_FLAT = {b: 0.5 for b in _OCT}


class FM:
    def __init__(self, name, bands, category="Catálogo", description=""):
        self.name = name
        self.category = category
        self.description = description
        self._b = dict(bands)

    def alpha_bands(self):
        return dict(self._b)

    def alpha(self, f):
        ks = sorted(self._b)
        f = float(min(max(f, ks[0]), ks[-1]))
        return float(np.interp(np.log(f), np.log(ks), [self._b[k] for k in ks]))


def _alpha_from_spec(spec):
    """α_random por banda de octava de un modelo conocido (oráculo)."""
    s = imp.build_surface(spec)
    return {b: float(np.asarray(s.alpha_random(np.array([float(b)]))).ravel()[0])
            for b in _OCT}


def _builds(spec):
    try:
        b = imp.build_surface(spec).beta(np.geomspace(30, 500, 40))
        return bool(np.all(np.isfinite(b)))
    except Exception as e:
        return f"build fallo: {e}"


_FBLOW = np.array([63.0, 125.0, 250.0])


def _eff_beta_re(res, mat):
    """Re(β) a θ=0 que usaría la simulación: del modelo si hay, o β real (Paris)."""
    if res.has_model and res.spec:
        return idf._model_beta_re(res.spec, _FBLOW)
    ab = np.array([mat.alpha(float(f)) for f in _FBLOW])
    return np.asarray(fm.beta_from_alpha_random(ab), dtype=float)


def _target_beta_re(mat):
    ab = np.array([mat.alpha(float(f)) for f in _FBLOW])
    return np.asarray(fm.beta_from_alpha_random(ab), dtype=float)


def _damping_ok(res, mat, tol=0.03, floor=0.4):
    """El amortiguamiento efectivo reproduce el del catálogo en graves y NO
    colapsa (eff >= floor*target). Es el invariante que evita el f_S falso."""
    eff = _eff_beta_re(res, mat)
    tgt = _target_beta_re(mat)
    close = float(np.max(np.abs(eff - tgt))) <= tol
    # colapso: target apreciable pero el efectivo muy por debajo
    collapse = bool(np.any((tgt > 0.02) & (eff < floor * tgt)))
    return close and not collapse, f"eff={np.round(eff,3)} tgt={np.round(tgt,3)}"


# ============================================================ P  parsers
check("P1 espesor mm", abs(idf.parse_thickness("Lana 40 mm") - 0.040) < 1e-9)
check("P1 espesor cm", abs(idf.parse_thickness("panel 3 cm") - 0.030) < 1e-9)
check("P1 espesor coma", abs(idf.parse_thickness("placa 12,5 mm") - 0.0125) < 1e-9)
check("P1 sin espesor -> None", idf.parse_thickness("lana mineral") is None)
check("P2 densidad kg", abs(idf.parse_density("lana 70 kg") - 70.0) < 1e-9)
check("P3 camara mm", abs(idf.parse_air_gap("con cámara de 100 mm") - 0.100) < 1e-9)
check("P3 sin camara -> None", idf.parse_air_gap("poroso solo") is None)

# ============================================================ N  sin modelo
rh = idf.classify_material(FM("Hormigón visto", _HARD))
check("N1 hormigon (duro _HARD) -> sin modelo, especifico (no avisa)",
      rh.kind == "hard" and not rh.has_model and not rh.nonspecific, rh.reason)
check("N1 duro nunca trae spec", rh.spec is None)
rau = idf.classify_material(FM("Audiencia de pie (1 persona/m2)", _HARD))
check("N2 audiencia -> beta real (personas)", rau.kind == "audiencia"
      and not rau.has_model and not rau.nonspecific, rau.reason)
rsm = idf.classify_material(FM("Sillas de madera", _HARD))
check("N3 sillas de madera -> duro (beta real)", rsm.kind == "hard"
      and not rsm.has_model, rsm.reason)
ru = idf.classify_material(FM("Lana de vidrio 50 mm", _FLAT, category="Personalizado"))
check("N4 material del usuario -> nonspecific aunque tenga keyword",
      ru.nonspecific and not ru.has_model and ru.kind == "usuario", ru.reason)
rf = idf.classify_material(FM("Absorbente genérico 50%", _FLAT))
check("N5 alpha plano sin keyword -> nonspecific (flat)",
      rf.nonspecific and rf.kind == "flat", rf.reason)
rpl = idf.classify_material(FM("Absorción del 50%", _FLAT, category="Otros",
                               description="Absorción plana del 50%"))
check("N6 'absorcion plana' NO es porous (plana != lana)",
      rpl.nonspecific and rpl.kind == "flat" and not rpl.has_model, rpl.reason)

# ============================================================ R  recuperacion (oraculo)
# Poroso conocido -> alpha rising -> clasifica porous y reproduce.
sp_por = {"type": "porous", "sigma": 20000.0, "thickness": 0.05,
          "model": "miki", "air_gap": 0.0}
mp = FM("Lana de vidrio 50 mm, 70 kg", _alpha_from_spec(sp_por))
rp = idf.classify_material(mp)
check("R1 poroso (α de un poroso real) -> type porous + modelo",
      rp.has_model and rp.spec["type"] == "porous", rp.reason)
check("R1 poroso reproduce el amortiguamiento (damping-match)", *(_damping_ok(rp, mp)))
check("R1 spec porous construye", _builds(rp.spec) is True)

# Membrana conocida (pico grave) -> clasifica membrane y reproduce.
sp_mem = {"type": "membrane", "mass_per_area": 4.0, "cavity_depth": 0.10,
          "damping": 0.35}
mm_ = FM("Panel membrana sobre cámara", _alpha_from_spec(sp_mem))
rm = idf.classify_material(mm_)
check("R2 membrana (α de una membrana real) -> type membrane + modelo",
      rm.has_model and rm.spec["type"] == "membrane", rm.reason)
check("R2 membrana reproduce el amortiguamiento", *(_damping_ok(rm, mm_)))

# Perforado conocido (pico medio) -> clasifica perforated.
sp_perf = {"type": "perforated", "thickness": 0.005, "hole_diam": 0.008,
           "ratio": 0.08, "cavity_depth": 0.08}
mpf = FM("Panel perforado de madera", _alpha_from_spec(sp_perf))
rpf = idf.classify_material(mpf)
check("R3 perforado (α de un perforado real) -> modelo que reproduce",
      rpf.has_model and _damping_ok(rpf, mpf)[0], rpf.reason)

# ============================================================ S  seleccion por forma
# keyword 'lana' (poroso) pero α con PICO GRAVE (membrana) -> la forma manda.
mem_alpha = _alpha_from_spec({"type": "membrane", "mass_per_area": 3.0,
                              "cavity_depth": 0.12, "damping": 0.3})
mov = FM("Panel con lana de vidrio detrás", mem_alpha)
rov = idf.classify_material(mov)
check("S1 keyword poroso + α pico-grave -> la FORMA elige membrana",
      rov.has_model and rov.spec["type"] == "membrane", rov.reason)
check("S1 override reproduce el amortiguamiento", *(_damping_ok(rov, mov)))
# keyword 'membrana' pero α PLANO -> β real (reactancia no justificada).
fmflat = FM("Placa de yeso (absorción plana)", {b: 0.20 for b in _OCT})
rfl = idf.classify_material(fmflat)
check("S2 keyword membrana + α plano -> β real (sin modelo espurio)",
      not rfl.has_model and rfl.spec is None, rfl.reason)
check("S2 β real reproduce el α exacto (damping-match)", *(_damping_ok(rfl, fmflat)))

# ============================================================ D  invariante anti-bug
# Materiales REALES del profesor (α de octava, del diagnóstico Control Ale.room):
_REAL = {
    "Emplacado del Control Room SMA": {63: 0.10, 125: 0.22, 250: 0.23, 500: 0.23,
                                       1000: 0.24, 2000: 0.22, 4000: 0.20, 8000: 0.20},
    "Techo de madera machihembrada y chapa": {63: 0.53, 125: 0.45, 250: 0.24,
                                              500: 0.12, 1000: 0.08, 2000: 0.06,
                                              4000: 0.05, 8000: 0.05},
    "Ventana de vidrios DVH": {63: 0.16, 125: 0.11, 250: 0.07, 500: 0.04,
                               1000: 0.03, 2000: 0.02, 4000: 0.02, 8000: 0.02},
    "Bass Trap pistonico 30 a 70 Hz": {63: 0.50, 125: 0.20, 250: 0.10, 500: 0.05,
                                       1000: 0.04, 2000: 0.03, 4000: 0.03, 8000: 0.03},
}
for nm, bands in _REAL.items():
    mat = FM(nm, bands, category="Tabiques y cerramientos multicapa")
    res = idf.classify_material(mat)
    ok, det = _damping_ok(res, mat)
    check(f"D [{nm[:24]}] amortiguamiento NO colapsa", ok,
          f"{'modelo '+res.spec['type'] if res.has_model else 'β real'} | {det}")

# ============================================================ honestidad + justif
check("F1 inespecifico/flat nunca trae spec",
      rf.spec is None and rpl.spec is None and ru.spec is None)
_allj = [rh, rau, rsm, ru, rf, rpl, rp, rm, rpf, rov, rfl]
check("G1 toda clasificacion trae justificacion no vacia",
      all(len(x.justification) > 20 for x in _allj),
      str([x.kind for x in _allj if len(x.justification) <= 20]))
check("G2 justificacion de poroso menciona «lana»",
      "lana" in rp.justification.lower())
check("G3 justificacion de flat menciona el coef. de variacion",
      "variaci" in rpl.justification.lower())

print()
print("=" * 64)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 64)
if _FAIL:
    print("  FALLARON:", ", ".join(_FAIL))
raise SystemExit(1 if _FAIL else 0)
