"""
bench_impedance_defaults.py - link material -> impedancia por default (feature 1-2)
===================================================================================
Valida el nucleo `impedance_defaults`: el mapeo keyword -> tipo de modelo, la
estimacion de parametros (espesor/densidad/camara), la deteccion de
inespecificos (usuario / alpha plano / sin keyword), y que cada spec propuesto
reconstruye una SurfaceImpedance valida via impedance.build_surface.

Correr:  PYTHONIOENCODING=utf-8 python bench_impedance_defaults.py
"""
from __future__ import annotations
import numpy as np

import impedance as imp
import impedance_defaults as idf

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


_POROUS = {63: 0.10, 125: 0.30, 250: 0.60, 500: 0.80,
           1000: 0.85, 2000: 0.90, 4000: 0.90, 8000: 0.90}
_HARD = {63: 0.02, 125: 0.02, 250: 0.03, 500: 0.03,
         1000: 0.04, 2000: 0.05, 4000: 0.05, 8000: 0.06}
_FLAT = {b: 0.5 for b in (63, 125, 250, 500, 1000, 2000, 4000, 8000)}


class FM:
    def __init__(self, name, bands=None, category="Catálogo", description=""):
        self.name = name
        self.category = category
        self.description = description
        self._b = dict(bands or _POROUS)

    def alpha_bands(self):
        return dict(self._b)

    def alpha(self, f):
        ks = sorted(self._b)
        f = float(min(max(f, ks[0]), ks[-1]))
        return float(np.interp(np.log(f), np.log(ks), [self._b[k] for k in ks]))


def _builds(spec):
    try:
        b = imp.build_surface(spec).beta(np.geomspace(30, 500, 40))
        return bool(np.all(np.isfinite(b)))
    except Exception as e:
        return f"build fallo: {e}"


# ---------------------------------------------------------------- parsers
check("P1 espesor mm", abs(idf.parse_thickness("Lana 40 mm") - 0.040) < 1e-9)
check("P1 espesor cm", abs(idf.parse_thickness("panel 3 cm") - 0.030) < 1e-9)
check("P1 espesor coma decimal", abs(idf.parse_thickness("placa 12,5 mm") - 0.0125) < 1e-9)
check("P1 sin espesor -> None", idf.parse_thickness("lana mineral") is None)
check("P2 densidad kg", abs(idf.parse_density("lana 70 kg") - 70.0) < 1e-9)
check("P3 camara mm", abs(idf.parse_air_gap("con cámara de 100 mm") - 0.100) < 1e-9)
check("P3 sin camara -> None", idf.parse_air_gap("poroso solo") is None)

# ---------------------------------------------------------------- poroso
r = idf.classify_material(FM("Lana de vidrio 50 mm, 70 kg"))
check("A1 lana -> porous con modelo", r.kind == "porous" and r.has_model
      and not r.nonspecific, r.reason)
check("A1 espesor leido 50 mm", abs(r.spec["thickness"] - 0.050) < 1e-9, str(r.spec))
check("A1 sigma del alpha (confianza alta)", r.confidence == "alta", r.confidence)
check("A1 spec porous construye", _builds(r.spec) is True, str(_builds(r.spec)))

# corcho / alfombra / cortina
rc = idf.classify_material(FM("Panel de corcho de 30 mm de espesor"))
check("A2 corcho -> porous 30 mm", rc.kind == "cork"
      and abs(rc.spec["thickness"] - 0.030) < 1e-9, str(rc.spec))
ra = idf.classify_material(FM("Alfombra gruesa (pelo largo)"))
check("A3 alfombra -> porous fino 10 mm", ra.kind == "carpet"
      and abs(ra.spec["thickness"] - 0.010) < 1e-9, str(ra.spec))
rcu = idf.classify_material(FM("Cortina de terciopelo pesado drapeado"))
check("A4 cortina -> porous + camara 50 mm por default",
      rcu.kind == "curtain" and abs(rcu.spec["air_gap"] - 0.050) < 1e-9, str(rcu.spec))

# ---------------------------------------------------------------- perforado
rp = idf.classify_material(FM("Panel perforado de madera, cámara 100 mm", _HARD))
check("B1 perforado -> Maa, cavidad 100 mm", rp.kind == "perforated"
      and rp.spec["type"] == "perforated"
      and abs(rp.spec["cavity_depth"] - 0.100) < 1e-9, str(rp.spec))
check("B1 espesor NO confunde la camara (default, no 100 mm)",
      rp.spec["thickness"] < 0.02, str(rp.spec["thickness"]))
check("B1 perforado confianza baja (subdeterminado)", rp.confidence == "baja")
check("B1 spec perforado construye", _builds(rp.spec) is True)
rm = idf.classify_material(FM("Absorbedor microperforado MPP", _POROUS))
check("B2 microperforado -> d<1mm", rm.kind == "perforated"
      and rm.spec["hole_diam"] < 1e-3, str(rm.spec))

# ---------------------------------------------------------------- membrana
rme = idf.classify_material(FM("Placa de yeso 12 mm sobre cámara 48 mm", _HARD))
check("C1 placa yeso -> membrana, m=espesor*densidad", rme.kind == "membrane"
      and abs(rme.spec["mass_per_area"] - 0.012 * 800.0) < 1e-6, str(rme.spec))
check("C1 membrana camara 48 mm", abs(rme.spec["cavity_depth"] - 0.048) < 1e-9)
check("C1 membrana confianza media (t y rho)", rme.confidence == "media", rme.confidence)
check("C1 spec membrana construye", _builds(rme.spec) is True)

# ---------------------------------------------------------------- duro / asientos
rh = idf.classify_material(FM("Hormigón visto", _HARD))
check("D1 hormigon -> sin modelo pero ESPECIFICO (no avisa)",
      rh.kind == "hard" and not rh.has_model and not rh.nonspecific, rh.reason)
# Asientos tapizados (con o sin gente) -> POROSO sin cámara.
rs = idf.classify_material(FM("Asientos tapizados", _POROUS))
check("D2 asientos tapizados -> poroso sin cámara", rs.kind == "upholstered"
      and rs.has_model and rs.spec["type"] == "porous"
      and rs.spec["air_gap"] == 0.0, str(rs.spec))
rso = idf.classify_material(FM("Asientos de teatro ocupados", _POROUS))
check("D2b asientos ocupados -> poroso (con gente)", rso.kind == "upholstered")
rsi = idf.classify_material(FM("Sillas de concierto muy tapizadas", _POROUS))
check("D2c sillas tapizadas -> poroso", rsi.kind == "upholstered")
# Audiencia -> beta real (personas).
rau = idf.classify_material(FM("Audiencia de pie (1 persona/m2)", _POROUS))
check("D3 audiencia -> beta real", rau.kind == "audiencia"
      and not rau.has_model and not rau.nonspecific, rau.reason)
rad = idf.classify_material(FM("Audiencia sobre asientos de madera (1/m2)", _POROUS))
check("D3b audiencia sobre asientos -> audiencia (beta real, no silla)",
      rad.kind == "audiencia", rad.reason)
# Sillas de madera/plastico -> duro.
rsm = idf.classify_material(FM("Sillas de madera", _HARD))
check("D4 sillas de madera -> duro (beta real)", rsm.kind == "hard"
      and not rsm.has_model, rsm.reason)

# ---------------------------------------------------------------- vidrios
rdv = idf.classify_material(FM("Doble vidrio de 2-3 mm, cámara de aire de 10 mm", _HARD))
check("V1 doble vidrio -> membrana + cámara 10 mm", rdv.kind == "doble_vidrio"
      and rdv.spec["type"] == "membrane"
      and abs(rdv.spec["cavity_depth"] - 0.010) < 1e-9, str(rdv.spec))
check("V1 doble vidrio spec construye", _builds(rdv.spec) is True)
rvi = idf.classify_material(FM("Vidrio de 6 mm", _HARD))
check("V2 vidrio solo -> membrana rígida", rvi.kind == "vidrio"
      and rvi.spec["type"] == "membrane"
      and abs(rvi.spec["mass_per_area"] - 0.006 * 2500) < 1e-6, str(rvi.spec))
rlv = idf.classify_material(FM("Cielorraso de lana de vidrio 40 mm, suspendido a 100 mm"))
check("V3 lana de vidrio NO es membrana (es poroso)", rlv.kind == "porous"
      and rlv.spec["type"] == "porous", rlv.reason)
check("V3 suspendido a 100 mm -> cámara 100 mm", abs(rlv.spec["air_gap"] - 0.100) < 1e-9,
      str(rlv.spec))

# ---------------------------------------------------------------- estriado / placa+lana
res = idf.classify_material(FM(
    "Panel estriado, franjas de 12,0 mm a intervalos de 20,0 mm, "
    "absorbente de 40 mm a 81 kg/m3, cavidad de 100,0 mm", _POROUS))
check("W1 estriado -> poroso, espesor del absorbente (40 mm, NO franjas 12 mm)",
      res.kind == "porous" and abs(res.spec["thickness"] - 0.040) < 1e-9, str(res.spec))
check("W1 estriado cavidad 100 mm", abs(res.spec["air_gap"] - 0.100) < 1e-9)
rpz = idf.classify_material(FM(
    "Placa de yeso de 10 mm sobre bastidor, 100 mm de lana mineral por detras", _HARD))
check("W2 placa+lana -> membrana con relleno poroso", rpz.kind == "membrane"
      and "porous_fill" in rpz.spec
      and abs(rpz.spec["porous_fill"]["thickness"] - 0.100) < 1e-9, str(rpz.spec))
check("W2 placa: m = 10mm x 800", abs(rpz.spec["mass_per_area"] - 0.010 * 800) < 1e-6)
check("W2 placa+lana spec construye", _builds(rpz.spec) is True)
# Terciopelo en contacto con la pared -> sin cámara.
rtc = idf.classify_material(FM("Terciopelo liviano colgado recto en contacto con la pared", _POROUS))
check("W3 terciopelo en contacto -> cortina SIN cámara",
      rtc.kind == "curtain" and rtc.spec["air_gap"] == 0.0, str(rtc.spec))
rtd = idf.classify_material(FM("Terciopelo pesado drapeado a mitad de area", _POROUS))
check("W3b terciopelo drapeado -> cortina CON cámara (default)",
      rtd.kind == "curtain" and rtd.spec["air_gap"] > 0.0, str(rtd.spec))

# ---------------------------------------------------------------- inespecificos
ru = idf.classify_material(FM("Lana de vidrio 50 mm", _POROUS,
                              category="Personalizado"))
check("E1 material del usuario -> nonspecific aunque tenga keyword",
      ru.nonspecific and not ru.has_model and ru.kind == "usuario", ru.reason)
rf = idf.classify_material(FM("Absorbente genérico 50%", _FLAT))
check("E2 alpha plano sin keyword -> nonspecific (flat)",
      rf.nonspecific and rf.kind == "flat", rf.reason)
rn = idf.classify_material(FM("Material raro XZ", _POROUS))
check("E3 sin keyword, no plano -> nonspecific (unknown)",
      rn.nonspecific and rn.kind == "unknown", rn.reason)
# Regresion: "plana" NO debe matchear "lana" (limite de palabra).
rpl = idf.classify_material(FM("Absorción del 50%", _FLAT,
                               category="Otros", description="Absorción plana del 50%"))
check("E4 'absorcion plana' NO es porous (plana != lana)",
      rpl.nonspecific and rpl.kind == "flat" and not rpl.has_model, rpl.reason)

# ---------------------------------------------------------------- honestidad
# Ningun material DURO recibe reactancia (spec None).
check("F1 duro nunca trae spec",
      idf.classify_material(FM("Hormigón visto", _HARD)).spec is None)
# Un inespecifico nunca trae spec.
check("F1 inespecifico nunca trae spec", rn.spec is None and rf.spec is None)

# ---------------------------------------------------------------- justificacion
_all = [r, rc, ra, rcu, rp, rm, rme, rh, rs, ru, rf, rn, rpl]
check("G1 toda clasificacion trae justificacion no vacia",
      all(len(x.justification) > 20 for x in _all),
      str([x.kind for x in _all if len(x.justification) <= 20]))
check("G2 justificacion de poroso menciona la keyword «lana»",
      "lana" in idf.classify_material(FM("Lana de vidrio 50 mm")).justification.lower())
check("G2 justificacion de perforado menciona «perforado»",
      "perforado" in rp.justification.lower(), rp.justification[:60])
check("G3 justificacion de flat menciona el coef. de variacion",
      "variaci" in rpl.justification.lower())

print()
print("=" * 64)
print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
print("=" * 64)
if _FAIL:
    print("  FALLARON:", ", ".join(_FAIL))
raise SystemExit(1 if _FAIL else 0)
