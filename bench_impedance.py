"""
bench_impedance.py - validacion de la Etapa 1a de Capa 0 (impedance.py)
=======================================================================
Escalera de validacion del plan (plan_modelado_Z.md seccion 4):
  T1  rigido -> alpha ~ 0, beta ~ 0
  T2  resistivo -> reproduce la alpha_random de Paris (puente con el modelo actual)
  T3  camara de aire -> resonancia de cuarto de onda en f = c/(4D) (exacto)
  T4  poroso + camara -> sube la absorcion en graves respecto de poroso solo
  T5  Delany-Bazley vs Miki -> concuerdan en la banda valida; Miki fisico a X<0.01
  T6  measured_Zf -> interpola exacto en los nodos
  T7  physicalidad -> alpha in [0,1] para una bateria de configuraciones

Corre:
    PYTHONIOENCODING=utf-8 /c/Users/aceve/anaconda3/python.exe bench_impedance.py
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


# ---------------------------------------------------------------------------
def t1_rigid():
    print("T1 - pared rigida")
    f = np.array([30.0, 100.0, 300.0])
    s = imp.rigid()
    a = s.alpha_random(f)
    b = np.abs(s.beta(f))
    check("alpha_random ~ 0", np.all(a < 1e-3), f"max={a.max():.2e}")
    check("|beta| ~ 0", np.all(b < 1e-3), f"max={b.max():.2e}")


def t2_resistive_bridge():
    print("T2 - resistivo reproduce Paris (puente con face_materials)")
    # Referencia: la integral de Paris del modelo actual.
    try:
        import face_materials as fm
        have_fm = True
    except Exception as e:
        have_fm = False
        print(f"    (face_materials no importable: {e})")
    f = np.array([50.0, 125.0, 250.0])
    for beta in (0.05, 0.1, 0.2, 0.4):
        a_imp = imp.resistive(beta).alpha_random(f)
        if have_fm:
            a_ref = float(fm._alpha_random_of_beta(np.array([beta]))[0])
            rel = np.abs(a_imp - a_ref) / a_ref
            check(f"beta={beta}: alpha_random={a_imp[0]:.4f} == Paris {a_ref:.4f}",
                  np.all(rel < 1e-3), f"max rel={rel.max():.2e}")
        else:
            # Sanity: monotona creciente con beta, en (0,1)
            check(f"beta={beta}: alpha_random en (0,1)",
                  bool(0 < a_imp[0] < 1), f"{a_imp[0]:.4f}")


def t3_air_gap_quarter_wave():
    print("T3 - camara de aire: resonancia de cuarto de onda f0 = c/(4D)")
    for D in (0.05, 0.10, 0.20):
        f0 = imp.C0 / (4.0 * D)
        # Solo aire, backing rigido: Z_s = -i Z0 cot(k0 D); Z_s=0 en f0.
        s = imp.multilayer([{"type": "air", "thickness": D}])
        z0 = np.abs(s.Z(f0))[0]
        z_low = np.abs(s.Z(0.25 * f0))[0]      # lejos de resonancia -> |Z| grande
        check(f"D={D*1e3:.0f}mm: |Z(f0={f0:.0f}Hz)| << Z0",
              z0 < 0.02 * imp.Z0, f"|Z(f0)|={z0:.2f}, |Z(f0/4)|={z_low:.0f}")


def t4_air_gap_boosts_bass():
    print("T4 - camara de aire sube la absorcion en graves (poroso fino)")
    f = np.array([125.0])
    sigma, t = 15000.0, 0.025                   # 25 mm de lana, sigma tipico
    a_no = imp.porous(sigma, t, model="miki").alpha_random(f)[0]
    a_gap = imp.porous(sigma, t, model="miki", air_gap=0.10).alpha_random(f)[0]
    check(f"alpha(125Hz): con camara {a_gap:.3f} > sin camara {a_no:.3f}",
          a_gap > a_no, f"delta={a_gap - a_no:+.3f}")


def t5_db_vs_miki():
    print("T5 - Delany-Bazley vs Miki")
    # En la banda valida (0.01<X<1) deben concordar a pocos %.
    sigma = 20000.0
    for X in (0.02, 0.1, 0.5):
        f = X * sigma / imp.RHO0
        zc_db, _ = imp.db_zc_kc(f, sigma)
        zc_mk, _ = imp.miki_zc_kc(f, sigma)
        rel = abs(zc_db[0] - zc_mk[0]) / abs(zc_db[0])
        check(f"X={X}: |Zc| DB={abs(zc_db[0]):.0f} ~ Miki={abs(zc_mk[0]):.0f}",
              rel < 0.15, f"rel={rel:.3f}")
    # A X<0.01 Delany-Bazley se vuelve no fisico (Re Zc<0); Miki se mantiene.
    Xlow = 0.003
    f = Xlow * sigma / imp.RHO0
    re_db = imp.db_zc_kc(f, sigma)[0].real[0]
    re_mk = imp.miki_zc_kc(f, sigma)[0].real[0]
    check(f"X={Xlow}: Miki fisico Re(Zc)>0 ({re_mk:.0f})", re_mk > 0,
          f"DB Re(Zc)={re_db:.0f}")

    # Patologia documentada de Delany-Bazley (Cox & D'Antonio p.182): en graves
    # (X<0.01) la alpha de superficie se vuelve NEGATIVA. Miki lo corrige. Se
    # valida como HECHO, no como fallo: es la razon de que Miki sea el default.
    fg = np.geomspace(20.0, 500.0, 60)
    a_db = imp.porous(50000, 0.025, "db").alpha_random(fg)
    a_mk = imp.porous(50000, 0.025, "miki").alpha_random(fg)
    check("Delany-Bazley se vuelve NO fisico en graves (alpha<0)",
          a_db.min() < 0.0, f"min alpha_DB={a_db.min():.3f}")
    check("Miki se mantiene fisico (alpha>=0) en toda la banda",
          a_mk.min() >= -1e-9, f"min alpha_Miki={a_mk.min():.3f}")


def t6_measured_interp():
    print("T6 - measured_Zf interpola exacto en los nodos")
    fq = np.array([50.0, 100.0, 200.0, 400.0])
    Z = np.array([300 - 200j, 250 - 100j, 420 - 30j, 410 + 10j])
    s = imp.measured_Zf(fq, Z)
    got = s.Z(fq)
    check("Z(nodos) == Z medida", np.allclose(got, Z, rtol=1e-9),
          f"max err={np.abs(got - Z).max():.2e}")
    # Punto intermedio: cae entre los vecinos (interpolacion lineal)
    zi = s.Z(150.0)[0]
    lo, hi = Z[1], Z[2]
    inside = (min(lo.real, hi.real) <= zi.real <= max(lo.real, hi.real))
    check("Z(150) interpolado entre vecinos", inside, f"{zi:.1f}")


def t7_physicality():
    print("T7 - physicalidad: alpha in [0,1]")
    # Miki (default) debe ser fisico en toda la banda modal. Delany-Bazley NO se
    # incluye aca: su no-fisicalidad en graves ya se valida en T5 (patologia
    # conocida, por eso Miki es el default).
    f = np.geomspace(20.0, 500.0, 60)
    configs = [
        imp.porous(10000, 0.05, "miki"),
        imp.porous(30000, 0.10, "miki", air_gap=0.05),
        imp.porous(50000, 0.025, "miki"),
        imp.multilayer([{"type": "porous", "sigma": 20000, "thickness": 0.05,
                         "model": "miki"},
                        {"type": "air", "thickness": 0.10}]),
    ]
    for s in configs:
        a = s.alpha_random(f)
        check(f"{s.label}: alpha in [0,1]",
              bool(np.all(a >= -1e-9) and np.all(a <= 1.0 + 1e-9)),
              f"min={a.min():.3f} max={a.max():.3f}")


def t8_jca():
    print("T8 - JCA (Johnson-Champoux-Allard, Etapa 1b)")
    # Material fibroso: phi~1, alpha_inf~1; Lambda desde sigma (relacion clasica
    # Lambda ~ sqrt(8*alpha_inf*eta/(sigma*phi))), Lambda' ~ 2*Lambda.
    phi, ainf, sigma = 0.98, 1.0, 20000.0
    Lam = np.sqrt(8.0 * ainf * imp.ETA / (sigma * phi))
    Lamp = 2.0 * Lam
    f = np.geomspace(30.0, 500.0, 40)

    # (a) convencion: Im(k_c) del mismo signo que Miki (e^{-iwt} -> Im(k)<0)
    fc = np.array([100.0, 300.0])
    _, kc_j = imp.jca_zc_kc(fc, phi, ainf, sigma, Lam, Lamp)
    _, kc_m = imp.miki_zc_kc(fc, sigma)
    check("T8a JCA: Im(k_c) mismo signo que Miki (convencion e^{-iwt})",
          bool(np.all(np.sign(kc_j.imag) == np.sign(kc_m.imag))),
          f"Im k_c JCA={kc_j.imag.round(3)}, Miki={kc_m.imag.round(3)}")

    # (b) fibroso: JCA ~ Miki en beta compleja (mismo orden, Re y -Im positivos)
    zc_j, _ = imp.jca_zc_kc(fc, phi, ainf, sigma, Lam, Lamp)
    zc_m, _ = imp.miki_zc_kc(fc, sigma)
    rel = np.abs(zc_j - zc_m) / np.abs(zc_m)
    check("T8b JCA fibroso ~ Miki en Z_c (mismo orden)",
          bool(np.all(rel < 0.4)), f"rel |Zc| = {rel.round(3)}")

    # (c) alpha fisica en toda la banda, con y sin camara
    a1 = imp.porous_jca(phi, ainf, sigma, Lam, Lamp, 0.05).alpha_random(f)
    a2 = imp.porous_jca(phi, ainf, sigma, Lam, Lamp, 0.05,
                        air_gap=0.10).alpha_random(f)
    check("T8c JCA: alpha in [0,1] (poroso 50mm)",
          bool(np.all(a1 >= -1e-9) and np.all(a1 <= 1.0 + 1e-9)),
          f"min={a1.min():.3f} max={a1.max():.3f}")
    check("T8d JCA: alpha in [0,1] (poroso 50mm + camara 100mm)",
          bool(np.all(a2 >= -1e-9) and np.all(a2 <= 1.0 + 1e-9)),
          f"min={a2.min():.3f} max={a2.max():.3f}")

    # (e) fibroso: alpha_random JCA cercana a Miki (mismo material)
    aj = imp.porous_jca(phi, ainf, sigma, Lam, Lamp, 0.05).alpha_random(f)
    am = imp.porous(sigma, 0.05, "miki").alpha_random(f)
    dmax = float(np.abs(aj - am).max())
    check("T8e JCA(fibroso) ~ Miki en alpha_random (dif < 0.15)",
          dmax < 0.15, f"max |dalpha| = {dmax:.3f}")

    # (f) camara de aire baja la absorcion a graves tambien en JCA
    a_lo_no = imp.porous_jca(phi, ainf, sigma, Lam, Lamp, 0.03).alpha_random(
        np.array([125.0]))[0]
    a_lo_gap = imp.porous_jca(phi, ainf, sigma, Lam, Lamp, 0.03,
                              air_gap=0.10).alpha_random(np.array([125.0]))[0]
    check("T8f JCA: camara sube absorcion en graves",
          a_lo_gap > a_lo_no, f"con {a_lo_gap:.3f} > sin {a_lo_no:.3f}")


def t9_oblique():
    print("T9 - incidencia oblicua (reaccion extendida, Etapa 2)")
    f = np.array([100.0, 300.0])
    sig, t = 20000.0, 0.05
    # (a) capa unica a theta=0 == forma cerrada -i z_c cot(k_c d) (bridge normal)
    s = imp.porous(sig, t, "miki")
    zc, kc = imp.miki_zc_kc(f, sig)
    z_ref = -1j * zc * np.cos(kc * t) / np.sin(kc * t)
    check("T9a Z(f,0) == forma cerrada de capa unica (bridge normal)",
          np.allclose(s.Z(f, 0.0), z_ref, rtol=1e-9),
          f"max dif {np.max(np.abs(s.Z(f, 0.0) - z_ref)):.2e}")
    # (b) flags de reaccion
    check("T9b porous es reaccion EXTENDIDA",
          s.is_locally_reacting is False, "")
    check("T9c rigid/resistive/measured_Zf son LOCALES",
          imp.rigid().is_locally_reacting and imp.resistive(0.1).is_locally_reacting
          and imp.measured_Zf([100, 200], [400 + 0j, 400 + 0j]).is_locally_reacting,
          "")
    # (d) Z varia con el angulo (la reaccion extendida hace algo)
    sg = imp.porous(sig, t, "miki", air_gap=0.10)
    z0, z45 = sg.Z(200.0, 0.0)[0], sg.Z(200.0, np.pi / 4)[0]
    check("T9d Z(f,theta) depende del angulo (poroso+camara)",
          abs(z45 - z0) / abs(z0) > 0.05, f"|dZ/Z|={abs(z45-z0)/abs(z0):.3f}")
    # (e) alpha(theta) fisica en varios angulos
    ok = all(bool(0 <= sg.alpha(f, th)[0] <= 1 and 0 <= sg.alpha(f, th)[1] <= 1)
             for th in (0.0, np.pi / 6, np.pi / 3))
    check("T9e alpha(theta) in [0,1] a 0, 30, 60 grados", ok, "")


def t10_measured_zft():
    print("T10 - measured_Zft (Z(f,theta) medida, reaccion extendida)")
    fq = np.array([50.0, 200.0, 500.0])
    tq = np.array([0.0, np.pi / 4, np.pi / 2 * 0.9])
    # Z sintetica que depende de f (fila) y theta (columna)
    Zg = np.array([[(300 - 100j) + 20 * i - 30j * j for j in range(3)]
                   for i in range(3)], dtype=complex)
    s = imp.measured_Zft(fq, tq, Zg)
    check("T10a is_locally_reacting False", s.is_locally_reacting is False, "")
    # exacto en un nodo (f, theta)
    got = s.Z(fq[1], tq[2])[0]
    check("T10b Z(nodo) == dato medido", abs(got - Zg[1, 2]) < 1e-9,
          f"{got:.1f} vs {Zg[1,2]:.1f}")
    # interior: entre los 4 vecinos en (f,theta)
    zi = s.Z(125.0, np.pi / 8)[0]
    lo = min(Zg[0, 0].real, Zg[1, 1].real)
    hi = max(Zg[0, 0].real, Zg[1, 1].real)
    check("T10c interior bilineal entre vecinos", lo - 1 <= zi.real <= hi + 1,
          f"Re={zi.real:.1f} en [{lo:.0f},{hi:.0f}]")


if __name__ == "__main__":
    print("=" * 64)
    print(" bench_impedance.py - Capa 0 Etapas 1a+1b+2a")
    print("=" * 64)
    t1_rigid()
    t2_resistive_bridge()
    t3_air_gap_quarter_wave()
    t4_air_gap_boosts_bass()
    t5_db_vs_miki()
    t6_measured_interp()
    t7_physicality()
    t8_jca()
    t9_oblique()
    t10_measured_zft()
    print("=" * 64)
    print(f" RESULTADO: {N_OK} OK, {N_FAIL} FAIL")
    print("=" * 64)
    raise SystemExit(1 if N_FAIL else 0)
