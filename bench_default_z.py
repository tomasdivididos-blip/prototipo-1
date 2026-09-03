# -*- coding: utf-8 -*-
"""bench_default_z.py -- Z(f) por default a cada material (Capa 0 automatica).

Verifica la decision C (hibrido por gate de forma del alpha):
  1. sigma_from_alpha: ajusta un poroso equivalente a materiales porosos y
     RECHAZA los duros/resonantes (gate amax + residual).
  2. INVARIANTE SAGRADO: Re(beta_solver) del SurfaceImpedance por default es
     bit-a-bit igual a beta_from_alpha_random(alpha_cat) para TODO material
     -> la absorcion medida / el amortiguamiento NO se tocan (no regresion).
  3. Duros (amax<0.15 o mal ajuste): Im(beta)=0 -> beta REAL -> identico al
     comportamiento previo (Z = Z0/beta_real).
  4. Porosos: Im(beta)!=0 con el signo/magnitud de Miki (reactancia injertada).

Convencion: el downstream de la perturbacion hace beta_solver = conj(Z0/Z).
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np

import impedance as imp
import face_materials as fm
from material_library import MaterialLibrary

try:
    from PyQt5.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
except Exception:
    _app = None
from acoustic_panel import AcousticPanel

FTEST = np.array([40.0, 63.0, 90.0, 125.0, 180.0, 250.0], dtype=float)
PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    ok = bool(cond)
    PASS += ok
    FAIL += (not ok)
    print(f"  [{'OK ' if ok else 'XX '}] {name}" + (f"  {extra}" if extra else ""))
    return ok


def beta_solver(surf, f):
    """Admitancia en la convencion del solver (e^{+iwt}): conj(Z0/Z)."""
    return np.conj(imp.Z0 / surf.Z(f))


def find(lib, sub):
    for m in lib.materials:
        if sub.lower() in m.name.lower():
            return m
    return None


def main():
    lib = MaterialLibrary("materials")
    mats = lib.materials
    print(f"Catalogo: {len(mats)} materiales\n")

    # -- 1. sigma_from_alpha: acepta poroso, rechaza duro -------------------
    print("1. Gate sigma_from_alpha (poroso vs duro)")
    porous_ex = find(lib, "espuma") or find(lib, "lana")
    hard_ex = find(lib, "Ladrillo") or find(lib, "Hormig")
    for m, expect in [(porous_ex, True), (hard_ex, False)]:
        if m is None:
            continue
        bands = m.alpha_bands()
        fb = np.array(sorted(bands), float)
        ac = np.array([bands[int(b)] for b in fb], float)
        s, r, ok = imp.sigma_from_alpha(ac, fb)
        check(f"{m.name[:30]:30s} porous={ok} (esperado {expect})",
              ok == expect, f"amax={ac.max():.2f} sigma={s if s else 0:.0f} resid={r if r else 0:.3f}")

    # -- 2. INVARIANTE: Re(beta_solver) == beta_from_alpha_random -----------
    print("\n2. Amortiguamiento intacto (Re beta == alpha->beta) en TODO material")
    worst = 0.0
    for m in mats:
        surf = AcousticPanel._material_surface(m)
        a = np.array([float(m.alpha(float(ff))) for ff in FTEST])
        expected_re = fm.beta_from_alpha_random(a)
        got = beta_solver(surf, FTEST)
        err = float(np.max(np.abs(got.real - expected_re)))
        worst = max(worst, err)
    check(f"max|Re(beta) - alpha->beta| sobre {len(mats)} materiales x {len(FTEST)} f",
          worst < 1e-9, f"worst={worst:.2e}")

    # -- 3. Duro: reactancia CERO (bit-a-bit como antes) --------------------
    print("\n3. Material duro -> Im(beta)=0 (identico al comportamiento previo)")
    if hard_ex is not None:
        surf = AcousticPanel._material_surface(hard_ex)
        b = beta_solver(surf, FTEST)
        check(f"{hard_ex.name[:30]:30s} Im(beta)==0",
              float(np.max(np.abs(b.imag))) == 0.0,
              f"max|Im|={np.max(np.abs(b.imag)):.2e}")
        # equivalencia con la Z real vieja
        a = np.array([float(hard_ex.alpha(float(ff))) for ff in FTEST])
        z_old = imp.Z0 / np.maximum(fm.beta_from_alpha_random(a), 1e-12)
        check("Z(default) == Z0/beta_real (regresion cero en duros)",
              float(np.max(np.abs(surf.Z(FTEST) - z_old))) < 1e-6)

    # -- 4. Poroso: reactancia presente + signo de Miki --------------------
    print("\n4. Material poroso -> Im(beta)!=0 con el signo de Miki")
    if porous_ex is not None:
        surf = AcousticPanel._material_surface(porous_ex)
        b = beta_solver(surf, FTEST)
        nz = float(np.max(np.abs(b.imag))) > 1e-4
        check(f"{porous_ex.name[:30]:30s} Im(beta)!=0", nz,
              f"Im(beta@63)={b.imag[1]:+.4f}")
        # signo: debe coincidir con la reactancia Miki cruda conj(Z0/zc)
        bands = porous_ex.alpha_bands()
        fb = np.array(sorted(bands), float)
        ac = np.array([bands[int(x)] for x in fb], float)
        s, _, _ = imp.sigma_from_alpha(ac, fb)
        zc, _ = imp.miki_zc_kc(FTEST, s)
        miki_im = np.imag(np.conj(imp.Z0 / zc))
        same_sign = bool(np.all(np.sign(b.imag[np.abs(b.imag) > 1e-6]) ==
                                np.sign(miki_im[np.abs(b.imag) > 1e-6])))
        check("signo(Im beta) == signo(reactancia Miki)", same_sign)

    # -- 5. Fraccion del catalogo que recibe reactancia --------------------
    print("\n5. Cobertura del gate sobre el catalogo")
    npor = 0
    for m in mats:
        bands = m.alpha_bands()
        fb = np.array(sorted(bands), float)
        ac = np.array([bands[int(b)] for b in fb], float)
        _, _, ok = imp.sigma_from_alpha(ac, fb)
        npor += ok
    frac = 100.0 * npor / max(len(mats), 1)
    check(f"porous={npor}/{len(mats)} ({frac:.0f}%) en rango razonable (10-70%)",
          10 <= frac <= 70)

    print(f"\n==== {PASS} OK / {FAIL} XX ====")
    return FAIL == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)
