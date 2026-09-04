"""
bench_capa0_audit.py - auditoria integral de Capa 0 (Etapa 4)
=============================================================
Verificacion transversal ANTES de conectar Capa 0 a la app (plan_modelado_Z.md
seccion 3, Etapa 4). No repite los benches de cada etapa; audita lo que cruza
etapas:
  A1  geometria IRREGULAR (pentagono / hexagono con taper / caja con twist) sobre
      _modal_incidence_angles y perturbation_xi_shift_{per_mode,extended}: sin
      NaN/inf, theta in [0,88deg], xi>=0, y COBERTURA (ninguna pared perdida, fix
      A1/A2 de nan_to_num->0).
  A2  pasividad Re(beta)>=0 y physicalidad alpha in [0,1] en TODA la escalera de
      modelos, barriendo banda y angulo.
  A3  rango de validez declarado y respetado por modelo (Delany-Bazley no fisico
      a X<0.01; Miki fisico; concordancia en 0.01<X<1).
  A4  convencion end-to-end (camara: el signo del corrimiento modal sigue la ley
      sign(f_new - f_n) = -sign(Im Z(f_n)); aparecen AMBOS signos al cruzar la
      resonancia del cavity).
  A5  convergencia: theta al refinar la malla; xi al refinar la cuadratura (subdiv).
  A6  call-path: rigido->xi=0; firma faltante->default/rigido; measured extrapola
      constante; grupos vacios->None (sin padding silencioso).

Correr:  QT_QPA_PLATFORM=offscreen python bench_capa0_audit.py
"""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

from geometry import make_room
from acoustic_mesh import build_volume_mesh
from acoustic_fem import build_KM, solve_modes, FieldEvaluator
import acoustic_analysis as aa
import face_materials as fm
import impedance as imp

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    (_PASS if cond else _FAIL).append(name)
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))


def build_room(n_walls=4, taper=0.0, twist=0.0, npm=2.4, n_modes=10):
    vr, tr, _e, _n = make_room(5.0, 4.0, 3.0, n_walls=n_walls, taper=taper,
                               twist=twist, roof_type="flat", subdiv_levels=0)
    nodes, tets = build_volume_mesh(vr, tr, n_per_meter=npm)
    K, M, _v = build_KM(nodes, tets)
    freqs, phis = solve_modes(K, M, n_modes=n_modes)
    loc = FieldEvaluator(nodes, tets)
    gr = fm.group_faces_by_planar_region(vr, tr)
    Vr = aa.compute_mesh_volume(vr, tr)
    return dict(vr=vr, tr=tr, nodes=nodes, freqs=freqs, phis=phis, loc=loc,
                gr=gr, Vr=Vr)


# ---------------------------------------------------------------------------
def a1_irregular():
    print("A1 - geometria irregular: finitud, rangos y cobertura")
    surf = imp.porous(15000.0, 0.05, "miki", air_gap=0.10)   # extendida
    for name, kw in [("pentagono", dict(n_walls=5)),
                     ("hexagono+taper", dict(n_walls=6, taper=0.25)),
                     ("caja+twist", dict(n_walls=4, taper=0.35, twist=0.15))]:
        R = build_room(**kw)
        gr, freqs, phis, loc, vr, tr, Vr = (R["gr"], R["freqs"], R["phis"],
                                            R["loc"], R["vr"], R["tr"], R["Vr"])
        # angulo por modo
        ang = fm._modal_incidence_angles(freqs, phis, loc, vr, tr, gr, subdiv=3)
        ang_ok = (ang is not None and np.all(np.isfinite(ang))
                  and np.all(ang >= 0.0) and np.all(ang <= np.radians(88.0) + 1e-9))
        # integrales de superficie (cobertura)
        Sg = fm._modal_surface_integrals(phis, loc, vr, tr, gr, subdiv=3)
        cov_ok = (Sg is not None and np.all(np.isfinite(Sg)) and np.all(Sg >= 0)
                  and np.all(Sg.max(axis=0) > 0))       # ninguna pared con 0 en todo modo
        # perturbacion extendida y normal
        xe = fm.perturbation_xi_shift_extended(
            freqs, phis, loc, vr, tr, gr, {s.signature: surf for s in gr}, Vr,
            subdiv=3)
        prov = lambda groups, fn: np.full(
            len(groups), np.conj(imp.Z0 / complex(surf.Z(fn, 0.0)[0])), dtype=complex)
        xn = fm.perturbation_xi_shift_per_mode(
            freqs, phis, loc, vr, tr, gr, {}, Vr, subdiv=3, beta_provider=prov)
        pert_ok = (xe is not None and xn is not None
                   and np.all(np.isfinite(xe[0])) and np.all(np.isfinite(xe[1]))
                   and np.all(xe[0] >= -1e-9))
        check(f"{name}: theta in [0,88deg] finito", ang_ok,
              f"theta_med={np.degrees(np.median(ang)):.1f}deg" if ang is not None else "")
        check(f"{name}: cobertura completa (Sg>0 en toda pared, finito)", cov_ok,
              f"{len(gr)} paredes, min area-cover={Sg.max(axis=0).min():.2e}"
              if Sg is not None else "")
        check(f"{name}: xi>=0 y f_new finito (extendida y normal)", pert_ok,
              f"xi in [{xe[0].min():.4f},{xe[0].max():.4f}]" if xe else "")


def a2_passivity():
    print("A2 - pasividad Re(beta)>=0 y alpha in [0,1] en toda la escalera")
    fg = np.geomspace(20.0, 5000.0, 240)
    thetas = np.radians([0, 15, 30, 45, 60, 75])
    Lam = np.sqrt(8.0 * 1.0 * imp.ETA / (20000.0 * 0.98))
    configs = [
        imp.rigid(),
        imp.resistive(0.1),
        imp.porous(20000.0, 0.05, "miki"),
        imp.porous(20000.0, 0.05, "miki", air_gap=0.10),
        imp.porous_jca(0.98, 1.0, 20000.0, Lam, 2 * Lam, 0.05, air_gap=0.05),
        imp.multilayer([{"type": "porous", "sigma": 20000, "thickness": 0.05,
                         "model": "miki"}, {"type": "air", "thickness": 0.10}]),
        imp.perforated(2e-3, 1.5e-3, 0.02, 0.10),
        imp.microperforated(0.8e-3, 0.3e-3, 0.01, 0.05),
        imp.membrane(3.0, 0.08, damping=0.02),
        imp.helmholtz(1e-4, 0.03, 1e-3, 1.0),
        imp.measured_Zf([50, 200, 500], [400 - 300j, 500 - 80j, 460 + 40j]),
    ]
    for s in configs:
        bad_a = bad_r = 0
        for th in thetas:
            a = s.alpha(fg, th)
            re = np.real(s.Z(fg, th))
            bad_a += int(np.sum((a < -1e-9) | (a > 1.0 + 1e-9)))
            bad_r += int(np.sum(re < -1e-6))
        ar = s.alpha_random(fg)
        bad_ar = int(np.sum((ar < -1e-9) | (ar > 1.0 + 1e-9)))
        check(f"{s.label[:52]}: alpha in [0,1] y Re(Z)>=0",
              bad_a == 0 and bad_r == 0 and bad_ar == 0,
              f"viol alpha={bad_a} ReZ={bad_r} rand={bad_ar}")


def a3_validity():
    print("A3 - rango de validez declarado por modelo")
    sigma = 20000.0
    # Dentro de 0.01<X<1: Delany-Bazley ~ Miki (pocos %)
    ok_band = True
    for X in (0.02, 0.1, 0.5):
        f = X * sigma / imp.RHO0
        zdb = imp.db_zc_kc(f, sigma)[0][0]
        zmk = imp.miki_zc_kc(f, sigma)[0][0]
        ok_band = ok_band and (abs(zdb - zmk) / abs(zdb) < 0.15)
    check("A3a Delany-Bazley ~ Miki en 0.01<X<1 (banda declarada valida)",
          ok_band, "")
    # X<0.01: Delany-Bazley se vuelve NO fisico (la capa porosa da alpha<0, Cox &
    # D'Antonio p.182); Miki lo corrige. La patologia esta en la ABSORCION de la
    # capa (|R|^2>1), no en Re(Zc) (que en DB es 1+0.0571 X^-0.754 > 0 siempre).
    fg = np.geomspace(20.0, 120.0, 40)                  # graves -> X<0.01
    a_db = imp.porous(50000.0, 0.025, "db").alpha_random(fg)
    a_mk = imp.porous(50000.0, 0.025, "miki").alpha_random(fg)
    check("A3b X<0.01: DB no fisico (alpha<0 en graves), Miki fisico (alpha>=0)",
          a_db.min() < 0.0 and a_mk.min() >= -1e-9,
          f"min alpha DB={a_db.min():.3f}, Miki={a_mk.min():.3f}")
    # Banda modal tipica de sala tratada: X efectivamente < 0.01 -> por eso Miki
    # es el default. Se documenta el rango.
    f_mod, sig_lana = 100.0, 15000.0
    X_mod = imp.RHO0 * f_mod / sig_lana
    check("A3c banda modal (100Hz, lana 15k) cae en X<0.01 -> Miki default",
          X_mod < 0.01, f"X={X_mod:.4f}")


def a4_convention_endtoend():
    print("A4 - convencion end-to-end: signo del corrimiento sigue -sign(Im Z)")
    R = build_room(n_walls=4, npm=2.6, n_modes=14)
    gr, freqs, phis, loc, vr, tr, Vr = (R["gr"], R["freqs"], R["phis"], R["loc"],
                                        R["vr"], R["tr"], R["Vr"])
    # Camara de aire cuya resonancia lambda/4 caiga DENTRO de la banda modal, para
    # que aparezcan modos como resorte (f<c/4D) y como masa (f>c/4D). Poroso fino
    # para acotar |beta| (perturbacion de 1er orden).
    f_mid = float(np.median(freqs))
    D = imp.C0 / (4.0 * f_mid)                          # c/4D = f_mid
    surf = imp.porous(8000.0, 0.02, "miki", air_gap=D)
    prov = lambda groups, fn: np.full(
        len(groups), np.conj(imp.Z0 / complex(surf.Z(fn, 0.0)[0])), dtype=complex)
    xi, f_new = fm.perturbation_xi_shift_per_mode(
        freqs, phis, loc, vr, tr, gr, {}, Vr, subdiv=3, beta_provider=prov)
    shift = f_new - freqs
    # Ley de signo por modo: sign(shift) == -sign(Im Z(f_n, 0)) (donde |shift| no es ruido)
    ImZ = np.array([float(np.imag(surf.Z(fn, 0.0)[0])) for fn in freqs])
    signif = np.abs(shift) > 1e-3
    law_ok = np.all(np.sign(shift[signif]) == -np.sign(ImZ[signif]))
    both = (np.any(shift[signif] > 0) and np.any(shift[signif] < 0))
    check(f"A4a ley de signo sign(f_new-f_n)=-sign(Im Z) (c/4D={f_mid:.0f}Hz)",
          law_ok, f"{int(signif.sum())}/{len(freqs)} modos significativos")
    check("A4b aparecen AMBOS signos de corrimiento al cruzar la resonancia",
          both, f"shift in [{shift.min():+.3f},{shift.max():+.3f}] Hz")
    check("A4c xi fisico (>=0, finito) con la camara",
          np.all(np.isfinite(xi)) and np.all(xi >= -1e-9),
          f"xi in [{xi.min():.4f},{xi.max():.4f}]")


def a5_convergence():
    print("A5 - convergencia: theta al refinar malla; xi al refinar la cuadratura")
    # (a) theta converge al refinar la MALLA (pentagono): media sobre los 4 modos
    #     mas bajos (orden estable) a npm creciente.
    def theta_mean_low(npm):
        R = build_room(n_walls=5, npm=npm, n_modes=8)
        ang = fm._modal_incidence_angles(R["freqs"], R["phis"], R["loc"],
                                         R["vr"], R["tr"], R["gr"], subdiv=3)
        return float(np.degrees(np.mean(ang[:4])))
    t_c, t_f = theta_mean_low(2.0), theta_mean_low(3.2)
    check("A5a theta(malla) converge (|d theta_medio| < 6 deg coarse->fine)",
          abs(t_f - t_c) < 6.0, f"coarse={t_c:.1f} fine={t_f:.1f} deg")
    # (b) xi converge al refinar la CUADRATURA (subdiv), que es el knob real de la
    #     integral de superficie (no la malla): |xi3-xi2| << |xi3-xi1|.
    R = build_room(n_walls=4, npm=2.6, n_modes=8)
    gr, freqs, phis, loc, vr, tr, Vr = (R["gr"], R["freqs"], R["phis"], R["loc"],
                                        R["vr"], R["tr"], R["Vr"])
    mat = type("M", (), {"alpha": lambda self, f: 0.20, "name": "a=0.2"})()
    g2m = {g.signature: mat for g in gr}
    xs = {sd: fm.perturbation_xi_per_mode(freqs, phis, loc, vr, tr, gr, g2m, Vr,
                                          subdiv=sd) for sd in (1, 2, 3)}
    d21 = float(np.max(np.abs(xs[2] - xs[3])))
    d01 = float(np.max(np.abs(xs[1] - xs[3])))
    check("A5b xi(cuadratura) converge (|xi2-xi3| < |xi1-xi3|)",
          d21 < d01 and d21 < 0.2 * max(d01, 1e-30),
          f"|xi1-xi3|={d01:.2e} |xi2-xi3|={d21:.2e}")


def a6_callpath():
    print("A6 - call-path: sin padding silencioso ni ramas muertas")
    R = build_room(n_walls=4, npm=2.4, n_modes=8)
    gr, freqs, phis, loc, vr, tr, Vr = (R["gr"], R["freqs"], R["phis"], R["loc"],
                                        R["vr"], R["tr"], R["Vr"])
    # (a) rigido -> xi = 0 (no absorbe)
    xr = fm.perturbation_xi_shift_extended(freqs, phis, loc, vr, tr, gr, {}, Vr,
                                           default_surf=imp.rigid(), subdiv=3)
    check("A6a rigido: xi ~ 0", xr is not None and np.all(np.abs(xr[0]) < 1e-6),
          f"max xi {np.max(np.abs(xr[0])):.2e}")
    # (b) firma faltante usa default_surf; faltante SIN default = rigido (beta=0).
    surf = imp.resistive(0.08)
    x_all = fm.perturbation_xi_shift_extended(
        freqs, phis, loc, vr, tr, gr, {s.signature: surf for s in gr}, Vr, subdiv=3)
    x_def = fm.perturbation_xi_shift_extended(
        freqs, phis, loc, vr, tr, gr, {}, Vr, default_surf=surf, subdiv=3)
    check("A6b firma faltante -> default_surf (identico a asignar a todas)",
          np.allclose(x_all[0], x_def[0], rtol=1e-9),
          f"max dif {np.max(np.abs(x_all[0]-x_def[0])):.2e}")
    x_none = fm.perturbation_xi_shift_extended(
        freqs, phis, loc, vr, tr, gr, {}, Vr, default_surf=None, subdiv=3)
    check("A6c firma faltante sin default -> rigido (xi=0), no crash",
          x_none is not None and np.all(np.abs(x_none[0]) < 1e-6),
          f"max xi {np.max(np.abs(x_none[0])):.2e}")
    # (d) measured_Zf extrapola CONSTANTE fuera del rango medido (no 0, no inf)
    s = imp.measured_Zf([100.0, 400.0], [400 - 100j, 420 + 20j])
    z_lo = s.Z(20.0)[0]      # debajo del rango
    z_hi = s.Z(2000.0)[0]    # encima del rango
    check("A6d measured_Zf extrapola constante (borde), finito",
          np.isfinite(z_lo) and np.isfinite(z_hi)
          and abs(z_lo - (400 - 100j)) < 1e-9 and abs(z_hi - (420 + 20j)) < 1e-9,
          f"Z(20)={z_lo:.0f} Z(2k)={z_hi:.0f}")
    # (e) grupos vacios -> None (guard, no excepcion)
    empty = fm.perturbation_xi_shift_per_mode(freqs, phis, loc, vr, tr, [], {}, Vr)
    check("A6e grupos vacios -> None (guard explicito)", empty is None, "")


if __name__ == "__main__":
    print("=" * 64)
    print(" bench_capa0_audit.py - Capa 0 Etapa 4 (auditoria integral)")
    print("=" * 64)
    a1_irregular()
    a2_passivity()
    a3_validity()
    a4_convention_endtoend()
    a5_convergence()
    a6_callpath()
    print("=" * 64)
    print(f" RESULTADO: {len(_PASS)} OK, {len(_FAIL)} FAIL")
    print("=" * 64)
    raise SystemExit(1 if _FAIL else 0)
