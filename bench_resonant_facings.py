"""
bench_resonant_facings.py - validacion de la Etapa 3 de Capa 0 (resonantes)
===========================================================================
Facings resonantes de impedance.py (panel perforado / microperforado Maa 1998 /
membrana masa-resorte) sobre cavidad, via el TMM ya existente. Fisica AISLADA:
no toca la app ni el FEM. Escalera de validacion (plan_modelado_Z.md seccion 3,
Etapa 3):
  T1  perforado: alpha(f) normal pico en f0 = (c/2pi) sqrt(ratio/(t_eff D))
  T2  membrana: pico en f0 = 60/sqrt(m D) = (1/2pi) sqrt(rho0 c^2/(m D))
  T3  microperforado (Maa): orificio angosto -> mas resistencia viscosa r que
      uno ancho (banda ancha sin poroso); r crece al achicar d
  T4  physicalidad + pasividad: alpha in [0,1] y Re(Z) >= 0 en banda y angulos
  T5  corrimiento de f_n CAMBIA DE SIGNO al cruzar la resonancia: Im(Z) pasa de
      resorte (<0, graves) a masa (>0, agudos) -> el shift de la perturbacion
      sign(f_new - f_n) = sign(Im(beta_imp)) se invierte
  T6  relleno poroso de la cavidad sube la absorcion fuera de resonancia (graves)
  T7  helmholtz(cuello+cavidad) resuena en f0 = (c/2pi) sqrt(S/(l_eff V))

Corre:
    PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_resonant_facings.py
"""
from __future__ import annotations
import numpy as np
import impedance as imp

N_OK = 0
N_FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global N_OK, N_FAIL
    tag = "OK  " if cond else "FAIL"
    if cond:
        N_OK += 1
    else:
        N_FAIL += 1
    print(f"  [{tag}] {name}" + (f"  -> {detail}" if detail else ""))


def _peak_freq(s: imp.SurfaceImpedance, fgrid, theta: float = 0.0) -> float:
    """Frecuencia (Hz) donde alpha(theta) es maxima en la grilla."""
    a = s.alpha(fgrid, theta)
    return float(fgrid[int(np.argmax(a))])


def _reactance_zero(s: imp.SurfaceImpedance, fgrid, theta: float = 0.0):
    """Primera f donde Im(Z) cruza de - (resorte) a + (masa): la resonancia
    fundamental EXACTA del facing sobre su cavidad. Interpola el cruce."""
    X = np.imag(s.Z(fgrid, theta))
    sgn = np.sign(X)
    idx = np.where((sgn[:-1] < 0) & (sgn[1:] >= 0))[0]
    if len(idx) == 0:
        return None
    i = int(idx[0])
    x0, x1 = X[i], X[i + 1]
    return float(fgrid[i] + (fgrid[i + 1] - fgrid[i]) * (-x0) / (x1 - x0))


# ---------------------------------------------------------------------------
def t1_perforated_resonance():
    print("T1 - panel perforado: resonancia de Helmholtz distribuida")
    # La resonancia fundamental cae en (0, c/4D): la reactancia del cavity (-cot)
    # es resorte que decrece de inf a 0, la del facing es masa que crece de 0 ->
    # cruzan una vez. El pico de alpha esta EXACTAMENTE en ese cruce (Im Z=0). La
    # formula lumped f0=(c/2pi)sqrt(ratio/(t_eff D)) es el limite k0 D -> 0
    # (cavity compacto); con cavidades de cm, k0 D ~ 1 y se aparta un ~10-20%.
    cases = [
        # (t, d, ratio, D)  espesor, diametro orificio, perforacion, camara.
        # Elegidos en regimen de cavidad compacta (k0 D <~ 0.85) para que la
        # formula lumped sea valida; con k0 D ~ 1 se aparta hasta ~30% (ver T1
        # nota): es la limitacion conocida del resonador de Helmholtz concentrado.
        (2e-3, 1.5e-3, 0.02, 0.10),
        (2e-3, 3e-3, 0.08, 0.05),
        (1e-3, 1.5e-3, 0.03, 0.08),
    ]
    for t, d, ratio, D in cases:
        s = imp.perforated(t, d, ratio, D)
        f_qw = imp.C0 / (4.0 * D)                      # lambda/4 de la cavidad
        fg = np.geomspace(40.0, 0.98 * f_qw, 2000)     # aisla el modo fundamental
        f_res = _reactance_zero(s, fg)                 # resonancia EXACTA
        fp = _peak_freq(s, fg)
        t_eff = t + 0.85 * d
        f0 = (imp.C0 / (2.0 * np.pi)) * np.sqrt(ratio / (t_eff * D))  # lumped
        tag = f"perf t={t*1e3:.1f} d={d*1e3:.1f} r={ratio*100:.0f}% D={D*1e3:.0f}mm"
        if f_res is None:
            check(f"{tag}: reactancia-cero existe", False, "sin cruce Im(Z)")
            continue
        kD = 2.0 * np.pi * f_res / imp.C0 * D
        rel_peak = abs(fp - f_res) / f_res
        rel_lump = abs(f0 - f_res) / f_res
        # (a) fisica exacta: el pico de alpha coincide con la reactancia-cero
        check(f"{tag}: pico alpha {fp:.0f}Hz == reactancia-cero {f_res:.0f}Hz",
              rel_peak < 0.06, f"rel={rel_peak:.3f}")
        # (b) la formula lumped aproxima la resonancia (limite k0 D -> 0)
        check(f"{tag}: f0 lumped {f0:.0f}Hz ~ f_res {f_res:.0f}Hz (k0D={kD:.2f})",
              rel_lump < 0.22, f"rel={rel_lump:.3f}")


def t2_membrane_resonance():
    print("T2 - membrana masa-resorte: f0 = 60/sqrt(m*D)")
    fg = np.geomspace(20.0, 800.0, 1200)
    for m, D in [(2.0, 0.10), (4.0, 0.05), (1.0, 0.08)]:
        s = imp.membrane(m, D, damping=0.03)
        f0_exact = (1.0 / (2.0 * np.pi)) * np.sqrt(
            imp.RHO0 * imp.C0 ** 2 / (m * D))
        f0_rule = 60.0 / np.sqrt(m * D)
        fp = _peak_freq(s, fg)
        rel = abs(fp - f0_exact) / f0_exact
        rule_ok = abs(f0_rule - f0_exact) / f0_exact < 0.02
        check(f"membrana m={m} D={D*1e3:.0f}mm: pico {fp:.0f}Hz ~ "
              f"f0 {f0_exact:.0f}Hz (regla 60/sqrt {f0_rule:.0f})",
              rel < 0.10 and rule_ok, f"rel={rel:.3f}")


def t3_maa_viscous():
    print("T3 - microperforado (Maa): la viscosidad crece al achicar el orificio")
    f = np.array([500.0])
    t, ratio = 1e-3, 0.01
    # Resistencia relativa r = Re(Z_face)/(rho0 c) para varios diametros.
    rs = []
    for d in (3e-3, 1e-3, 0.3e-3, 0.1e-3):
        r = float(np.real(imp.maa_zface(f, t, d, ratio)[0])) / imp.Z0
        rs.append(r)
        print(f"      d={d*1e3:.2f}mm -> r={r:.3f}")
    rs = np.array(rs)
    check("r crece monotono al achicar d (perforado -> microperforado)",
          bool(np.all(np.diff(rs) > 0)), f"r={rs.round(3)}")
    # Un microperforado (d=0.2mm) sin poroso ya da banda ancha: alpha_random > 0.3
    # en una decada alrededor de la resonancia.
    fg = np.geomspace(200.0, 2000.0, 400)
    smpp = imp.microperforated(0.8e-3, 0.2e-3, 0.008, 0.05)
    a = smpp.alpha_random(fg)
    frac = float(np.mean(a > 0.3))
    check("MPP sin poroso: alpha_random>0.3 en gran parte de la banda",
          frac > 0.4, f"fraccion={frac:.2f}, alpha_max={a.max():.2f}")


def t4_physicality():
    print("T4 - physicalidad (alpha in [0,1]) y pasividad (Re Z >= 0)")
    fg = np.geomspace(30.0, 2000.0, 300)
    configs = [
        imp.perforated(1e-3, 2e-3, 0.05, 0.10),
        imp.microperforated(0.8e-3, 0.3e-3, 0.01, 0.05),
        imp.membrane(3.0, 0.08, damping=0.02),
        imp.perforated(1e-3, 2e-3, 0.05, 0.10,
                       porous_fill={"sigma": 15000.0, "thickness": 0.03}),
    ]
    for s in configs:
        ok_a = True
        ok_r = True
        for th in (0.0, np.pi / 6, np.pi / 3):
            a = s.alpha(fg, th)
            re = np.real(s.Z(fg, th))
            ok_a = ok_a and bool(np.all(a >= -1e-9) and np.all(a <= 1.0 + 1e-9))
            ok_r = ok_r and bool(np.all(re >= -1e-6))
        ar = s.alpha_random(fg)
        ok_ar = bool(np.all(ar >= -1e-9) and np.all(ar <= 1.0 + 1e-9))
        check(f"{s.label}: alpha in [0,1] (0/30/60 y aleatoria) y Re(Z)>=0",
              ok_a and ok_r and ok_ar, "")


def t5_shift_sign_flip():
    print("T5 - el corrimiento de f_n CAMBIA DE SIGNO al cruzar la resonancia")
    # Perforado con resonancia clara. Debajo de f0: reactancia neta de RESORTE
    # (Im(Z)<0). Encima: de MASA (Im(Z)>0). En la perturbacion el shift es
    #   f_new - f_n = +(c/2) S Im(beta_imp)/(2pi),  S>0 (integral de superficie),
    # con beta_imp = rho0 c / Z (convencion e^{-iwt} de impedance.py). Luego
    #   sign(f_new - f_n) = sign(Im(beta_imp)) = -sign(Im(Z)).
    t, d, ratio, D = 1e-3, 2e-3, 0.05, 0.10
    s = imp.perforated(t, d, ratio, D)
    t_eff = t + 0.85 * d
    f0 = (imp.C0 / (2.0 * np.pi)) * np.sqrt(ratio / (t_eff * D))
    f_lo, f_hi = 0.5 * f0, 2.0 * f0

    ImZ_lo = float(np.imag(s.Z(f_lo)[0]))
    ImZ_hi = float(np.imag(s.Z(f_hi)[0]))
    check(f"debajo de f0 ({f_lo:.0f}Hz): Im(Z)<0 (resorte)",
          ImZ_lo < 0, f"Im(Z)={ImZ_lo:.1f}")
    check(f"encima de f0 ({f_hi:.0f}Hz): Im(Z)>0 (masa)",
          ImZ_hi > 0, f"Im(Z)={ImZ_hi:.1f}")

    # Shift de la perturbacion (S>0 y c>0 no cambian el signo): sign = sign(Im beta)
    def shift_sign(fq):
        beta = imp.Z0 / s.Z(fq)[0]            # beta_imp (e^{-iwt})
        return np.sign(np.imag(beta))         # = sign(f_new - f_n)
    ss_lo, ss_hi = shift_sign(f_lo), shift_sign(f_hi)
    check("sign(f_new - f_n) se INVIERTE de graves a agudos",
          ss_lo != 0 and ss_hi != 0 and ss_lo != ss_hi,
          f"shift graves {ss_lo:+.0f}, agudos {ss_hi:+.0f}")


def t6_porous_fill():
    print("T6 - relleno poroso de la cavidad sube la absorcion en graves")
    t, d, ratio, D = 1e-3, 2e-3, 0.05, 0.10
    t_eff = t + 0.85 * d
    f0 = (imp.C0 / (2.0 * np.pi)) * np.sqrt(ratio / (t_eff * D))
    f_lo = np.array([0.4 * f0])                # bien debajo de la resonancia
    a_empty = imp.perforated(t, d, ratio, D).alpha_random(f_lo)[0]
    a_fill = imp.perforated(
        t, d, ratio, D,
        porous_fill={"sigma": 15000.0, "thickness": 0.06}).alpha_random(f_lo)[0]
    check(f"alpha({0.4*f0:.0f}Hz): con relleno {a_fill:.3f} > vacia {a_empty:.3f}",
          a_fill > a_empty, f"delta={a_fill - a_empty:+.3f}")


def t7_helmholtz():
    print("T7 - Helmholtz (cuello+cavidad) resuena en (c/2pi) sqrt(S/(l_eff V))")
    fg = np.geomspace(30.0, 1200.0, 1200)
    # Cuello 1 cm^2, largo 3 cm, cavidad 1 L, distribuido sobre 1 m^2 de pared.
    for S, l, V, A in [(1e-4, 0.03, 1e-3, 1.0), (4e-4, 0.02, 2e-3, 1.0)]:
        s = imp.helmholtz(S, l, V, A)
        d = 2.0 * np.sqrt(S / np.pi)
        l_eff = l + 0.85 * d
        Vloc = V / A                            # profundidad de cavidad equivalente
        f0 = (imp.C0 / (2.0 * np.pi)) * np.sqrt((S / A) / (l_eff * Vloc))
        fp = _peak_freq(s, fg)
        rel = abs(fp - f0) / f0
        check(f"Helmholtz S={S*1e4:.0f}cm2 l={l*1e3:.0f}mm V={V*1e3:.0f}L: "
              f"pico {fp:.0f}Hz ~ f0 {f0:.0f}Hz",
              rel < 0.15, f"rel={rel:.3f}")


if __name__ == "__main__":
    print("=" * 64)
    print(" bench_resonant_facings.py - Capa 0 Etapa 3 (resonantes)")
    print("=" * 64)
    t1_perforated_resonance()
    t2_membrane_resonance()
    t3_maa_viscous()
    t4_physicality()
    t5_shift_sign_flip()
    t6_porous_fill()
    t7_helmholtz()
    print("=" * 64)
    print(f" RESULTADO: {N_OK} OK, {N_FAIL} FAIL")
    print("=" * 64)
    raise SystemExit(1 if N_FAIL else 0)
