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


if __name__ == "__main__":
    print("=" * 64)
    print(" bench_impedance.py - Etapa 1a de Capa 0")
    print("=" * 64)
    t1_rigid()
    t2_resistive_bridge()
    t3_air_gap_quarter_wave()
    t4_air_gap_boosts_bass()
    t5_db_vs_miki()
    t6_measured_interp()
    t7_physicality()
    print("=" * 64)
    print(f" RESULTADO: {N_OK} OK, {N_FAIL} FAIL")
    print("=" * 64)
    raise SystemExit(1 if N_FAIL else 0)
