"""bench_columnas.py — Oraculos de columnas piso-techo (v2.88, Fase 3).

El motor es el MISMO carve de furniture.py (ya validado en bench_furniture.py).
Lo NUEVO de una columna es el caso TUNEL piso-techo (genero 1): los muebles son
vacios flotantes/apoyados, una columna atraviesa el dominio de lado a lado. Estos
4 oraculos (plan_columnas.md §6) son el gate fisico del feature. Todos falsables.

  O1. Reduccion de la huella -> 0: columna cada vez mas fina en un shoebox 5x4x3
      conocido -> fn(columna) -> fn(sala vacia) (error decreciente, -> 0). La sala
      vacia coincide con el analitico (ancla).
  O2. Convergencia en npm: para una columna fija, el corrimiento Dfn se estabiliza
      al subir npm (Cauchy: |Df(npm) - Df(npm+1)| decrece). La columna fina es el
      caso mas exigente de resolucion; reporta el npm que estabiliza.
  O3. Simetria: columna centrada en una sala de base cuadrada -> el par degenerado
      (1,0,0)/(0,1,0) SIGUE degenerado (la columna simetrica no lo parte) y AMBOS
      se corren (la columna actua).
  O4. Regimen perturbativo ka<<1 (Morse & Ingard §9.2, perturbacion de cavidad por
      obstaculo pequeno): el corrimiento escala con el AREA de la seccion (Dw ~ a^2,
      porque DV ~ a^2 y el integrando es ~ cte en la columna fina). Doblar el lado
      cuadruplica el corrimiento. Falsa si escalara lineal (~2x) en vez de ~4x.
  Regresion: sin columnas, malla identica bit a bit (heredado, se re-chequea).

Correr:  python bench_columnas.py
"""

import numpy as np

import geometry
import acoustic_mesh
import acoustic_fem
import furniture as fu


results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def room_mesh(Lx, Ly, Lz, npm=4.0):
    v, t, *_ = geometry.make_room(Lx, Ly, Lz, n_walls=4)
    nodes, tets = acoustic_mesh.build_volume_mesh(v, t, n_per_meter=npm)
    return v, nodes, tets


def solve(nodes, tets, n_modes=15):
    K, M, _ = acoustic_fem.build_KM(nodes, tets)
    freqs, _ = acoustic_fem.solve_modes(K, M, n_modes=n_modes)
    return np.asarray(freqs)


def nearest(freqs, f0):
    freqs = np.asarray(freqs)
    return float(freqs[np.argmin(np.abs(freqs - f0))])


def carve_column(surface_v, nodes, tets, *, kind="box", side=0.5, diam=None,
                 center=(0.0, 0.0)):
    """Talla una columna piso-techo centrada en `center`. Devuelve (nodes2,tets2,info,furn)."""
    if kind == "cylinder":
        col = fu.make_column("cylinder", diameter=(diam if diam else side),
                             position=(center[0], center[1], 0.0))
    else:
        col = fu.make_column("box", diameter=side, depth=side,
                             position=(center[0], center[1], 0.0))
    fu.sync_column_height(col, surface_v)                 # altura = alto de sala
    n2, t2, info = fu.carve_mesh(nodes, tets, [col])
    return n2, t2, info, col


# ---------------------------------------------------------------------------
print("O0: regresion — sin columnas, malla intacta")
v0, nodes0, tets0 = room_mesh(5, 4, 3, npm=4.0)
n2, t2, info = fu.carve_mesh(nodes0, tets0, [])
check("nodes/tets identicos bit a bit",
      np.array_equal(n2, nodes0) and np.array_equal(t2, tets0),
      f"{len(nodes0)} nodos, {len(tets0)} tets")

# ---------------------------------------------------------------------------
print("\nO1: reduccion de la huella -> 0 (columna -> sala vacia -> analitico)")
# Ancla: sala vacia vs analitico shoebox.
f_empty = solve(nodes0, tets0, n_modes=15)


def analytic(Lx, Ly, Lz, fmax=120, c=343.0):
    out = []
    for nx in range(4):
        for ny in range(4):
            for nz in range(3):
                if nx == ny == nz == 0:
                    continue
                f = c / 2 * np.sqrt((nx/Lx)**2 + (ny/Ly)**2 + (nz/Lz)**2)
                if f <= fmax:
                    out.append(f)
    return np.array(sorted(out))


anchors = [(34.3, "100"), (42.875, "010"), (57.17, "001"), (68.6, "200")]
e_anchor = max(abs(nearest(f_empty, f0) - f0) / f0 for f0, _ in anchors) * 100
check("sala vacia ~ analitico (<4%)", e_anchor < 4.0, f"max err {e_anchor:.1f}%")

# Columna centrada, lado decreciente. max|Df/f| sobre los axiales anclados.
def shift_metric(fr):
    return max(abs(nearest(fr, f0) - nearest(f_empty, f0)) / nearest(f_empty, f0)
               for f0, _ in anchors) * 100

sides = [0.75, 0.50, 0.25, 0.10]      # 0.10 < paso de malla (0.25) -> sub-resolucion
S = []
ntets = []
for sd in sides:
    nc, tc, inf, _ = carve_column(v0, nodes0, tets0, kind="box", side=sd)
    S.append(shift_metric(solve(nc, tc, n_modes=15)))
    ntets.append(inf["n_tets_removed"])
    print(f"    lado {sd:.2f} m -> max|Df/f| = {S[-1]:.3f}%  "
          f"(V {inf['V_removed_mesh']:.2f} m3, {inf['n_tets_removed']} tets)")
check("corrimiento decrece al afinar la columna (monotono)",
      S[0] > S[1] > S[2] > S[3], " > ".join(f"{s:.3f}" for s in S) + " %")
check("columna sub-malla (0.10 m < paso) -> efecto -> 0 (<0.25%)", S[-1] < 0.25,
      f"lado 0.10 m: {S[-1]:.3f}% ({ntets[-1]} tets removidos)")

# ---------------------------------------------------------------------------
print("\nO2: convergencia en npm (columna fija, Df estabiliza)")
# Columna cuadrada 0.5 m centrada; Df del (2,0,0) vs sala vacia al MISMO npm.
f200 = 343 / 5.0
dfs = []
for npm in (3.0, 4.0, 5.0):
    vv, nn, tt = room_mesh(5, 4, 3, npm=npm)
    fe = nearest(solve(nn, tt, n_modes=15), f200)
    nc, tc, _, _ = carve_column(vv, nn, tt, kind="box", side=0.5)
    fc = nearest(solve(nc, tc, n_modes=15), f200)
    dfs.append((fc - fe) / fe * 100)
    print(f"    npm {npm:.0f} -> Df(2,0,0) = {dfs[-1]:+.3f}%")
check("Df(2,0,0) > 0 en todo npm (antinodo en el centro: sube)",
      all(d > 0 for d in dfs), ", ".join(f"{d:+.3f}%" for d in dfs))
spread = max(dfs) - min(dfs)
check("Df(2,0,0) estable en npm (spread < 0.1%): convergido",
      spread < 0.1, f"spread {spread:.3f}% sobre npm 3/4/5")

# ---------------------------------------------------------------------------
print("\nO3: simetria — columna centrada en base cuadrada no parte la degeneracion")
# ROBUSTECIDO (auditoria MAYOR-2): el split del par (1,0,0)/(0,1,0) con la columna
# CENTRADA NO es cero exacto ni converge monotono a cero; es un ARTEFACTO acotado de
# la voxelizacion Freudenthal (la diagonal de Kuhn rompe la simetria x<->y en la
# frontera escalonada de la columna). El oraculo honesto: (a) ese split se mantiene
# PEQUENO y acotado barriendo npm (no un solo valor afortunado), y (b) es MUY MENOR
# que el split FISICO de una columna DESCENTRADA (la discriminacion cualitativa que
# importa). f del par = 343/8 = 42.875 Hz.
fdeg = 343 / 8.0


def pair_split(freqs):
    idx = np.argsort(np.abs(np.asarray(freqs) - fdeg))[:2]
    fr = np.asarray(freqs)
    return abs(fr[idx[0]] - fr[idx[1]]), fr[idx].mean()


splits_centered = []
split_desc = shift_pair = f_pair_emp = f_pair_col = None
for npm in (4.0, 5.0, 6.0):
    vq, nq, tq = room_mesh(4, 4, 3, npm=npm)
    fe_q = solve(nq, tq, n_modes=15)
    s_empty, f_emp = pair_split(fe_q)
    ncc, tcc, _, _ = carve_column(vq, nq, tq, kind="box", side=0.5)      # centrada
    s_cent, f_col = pair_split(solve(ncc, tcc, n_modes=15))
    splits_centered.append(s_cent)
    print(f"    npm {npm:.0f} -> split centrado = {s_cent:.4f} Hz ({s_cent/fdeg*100:.4f}%)"
          f" | split sala vacia = {s_empty:.4f} Hz")
    if npm == 4.0:
        # Contraprueba fisica al mismo npm: columna DESCENTRADA parte el par.
        nd, td, _, _ = carve_column(vq, nq, tq, kind="box", side=0.5, center=(0.5, 0.0))
        split_desc, _ = pair_split(solve(nd, td, n_modes=15))
        f_pair_emp, f_pair_col = f_emp, f_col
        shift_pair = (f_col - f_emp) / f_emp * 100

max_split = max(splits_centered)
# Cota de artefacto: la auditoria midio <=0.06% del par (~0.026 Hz) a npm 4-7; 0.2%
# (~0.086 Hz) deja margen sin dejar pasar un split fisico (la descentrada da ~1.6%).
check("split CENTRADO acotado como artefacto (<0.2% del par) en todo npm 4/5/6",
      max_split < 0.002 * fdeg,
      f"max {max_split:.4f} Hz = {max_split/fdeg*100:.4f}% sobre npm 4/5/6")
check("la columna DESCENTRADA SI parte el par (split fisico >> artefacto)",
      split_desc > 10.0 * max_split,
      f"descentrada {split_desc:.3f} Hz ({split_desc/fdeg*100:.2f}%) vs artefacto "
      f"{max_split:.4f} Hz")
check("el par SI se corre (la columna centrada actua)", abs(shift_pair) > 0.1,
      f"{f_pair_emp:.2f} -> {f_pair_col:.2f} Hz  ({shift_pair:+.3f}%)")

# ---------------------------------------------------------------------------
print("\nO4: regimen perturbativo ka<<1 — Dw ~ a^2 (doblar el lado -> ~4x)")
# El escalado a^2 vale cuando la columna es FINA frente a la longitud de onda del
# MODO (k_modo * a << 1). (2,0,0) tiene lambda corta (2.5 m): lados 0.5/1.0 dan
# k*a ~ 0.3/0.6 (NO <<1) y el escalado satura. Se usa (1,0,0), lambda=10 m: lados
# 0.25/0.5 dan k*a = 0.08/0.16 << 1. (1,0,0) tiene NODO de presion en el centro
# -> el corrimiento lo domina -rho|u|^2 (antinodo de velocidad), BAJA, ~ cte sobre
# la columna fina -> Dw ~ area ~ lado^2. Doblar el lado -> ~4x.
k100 = 2 * np.pi * 34.3 / 343.0        # numero de onda del modo (1,0,0)

def df100(side):
    nc, tc, _, _ = carve_column(v0, nodes0, tets0, kind="box", side=side)
    fc = nearest(solve(nc, tc, n_modes=15), 34.3)
    fe = nearest(f_empty, 34.3)
    return (fc - fe) / fe * 100

d_small = df100(0.25)
d_big = df100(0.50)
ratio = abs(d_big) / abs(d_small) if d_small else 0.0
print(f"    lado 0.25 (k*a={k100*0.125:.3f}) Df={d_small:+.3f}%  |  "
      f"lado 0.50 (k*a={k100*0.25:.3f}) Df={d_big:+.3f}%  ->  ratio {ratio:.2f}")
check("ambos corrimientos negativos (nodo de presion: baja)",
      d_small < 0 and d_big < 0, f"{d_small:+.3f}% , {d_big:+.3f}%")
check("escala con el area (~4x; descarta lineal ~2x)", 2.5 <= ratio <= 6.0,
      f"ratio {ratio:.2f} (esperado ~4 por Dw~a^2, M&I §9.2)")

# ---------------------------------------------------------------------------
print("\nO5: guarda de conectividad (tabique parte el aire -> aviso, sin 0 Hz espurio)")
# Una columna que cruza de pared a pared parte el dominio de aire en 2
# componentes. Antes (bug MAYOR-1 del auditor): el solver descartaba UN solo
# modo cero y quedaba un 0 Hz espurio contaminando Bonello/FSI/Fazenda/FRF.
# Fix: carve_mesh cuenta componentes y avisa; solve_modes descarta TODOS los ~0.
vt, nt, tt = room_mesh(4, 3, 2.6, npm=5.0)
col_wall = fu.make_column("box", diameter=0.3, depth=3.2, position=(0.0, 0.0, 0.0))
fu.sync_column_height(col_wall, vt)
n2w, t2w, info_w = fu.carve_mesh(nt, tt, [col_wall])
Kw, Mw, _ = acoustic_fem.build_KM(n2w, t2w)
f_raw, _ = acoustic_fem.solve_modes(Kw, Mw, n_modes=15, drop_zero_mode=False)
f_kept, _ = acoustic_fem.solve_modes(Kw, Mw, n_modes=15, drop_zero_mode=True)
n_zero_raw = int(np.count_nonzero(np.asarray(f_raw) < 1.0))
n_zero_kept = int(np.count_nonzero(np.asarray(f_kept) < 1.0))
check("tabique detectado como 2 componentes de aire",
      info_w["n_air_components"] == 2, f"n_air_components={info_w['n_air_components']}")
check("avisa del tabique (warning PARTIDO)",
      any("PARTIDO" in w for w in info_w["warnings"]),
      f"{len(info_w['warnings'])} warnings")
check("el dominio partido genera 2 modos cero crudos",
      n_zero_raw == 2, f"{n_zero_raw} modos < 1 Hz sin drop")
check("solve_modes descarta TODOS los ceros (sin 0 Hz espurio)",
      n_zero_kept == 0, f"{n_zero_kept} modos < 1 Hz tras drop")
# Contraprueba: columna interior sigue conexa, 1 solo cero, sin aviso.
col_in = fu.make_column("box", diameter=0.4, depth=0.4, position=(0.0, 0.0, 0.0))
fu.sync_column_height(col_in, v0)
_ni, _ti, info_in = fu.carve_mesh(nodes0, tets0, [col_in])
check("contraprueba: columna interior -> 1 componente, sin aviso de tabique",
      info_in["n_air_components"] == 1
      and not any("PARTIDO" in w for w in info_in["warnings"]),
      f"n_air_components={info_in['n_air_components']}, "
      f"warnings={info_in['warnings']}")

# ---------------------------------------------------------------------------
print("\nO6: techo inclinado — prisma a z_max GLOBAL talla solo el aire que existe")
# Afirmacion titular del feature, antes SIN bench en el repo (la auditoria la
# verifico por fuera). Sala cuna: piso z=0, techo de z=2 (x=0) a z=4 (x=5). Una
# columna sincronizada al z_max GLOBAL (4) NO debe tallar aire POR ENCIMA del techo
# LOCAL en su huella -> un perfil por huella tallaria los MISMOS tets (refinamiento
# de dibujo, no de fisica; de acuerdo con el autor para techos monotonos).
def _ceiling_z(x):
    return 2.0 + (2.0 / 5.0) * np.asarray(x, float)

_corners = np.array([
    [0, 0, 0], [5, 0, 0], [5, 4, 0], [0, 4, 0],
    [0, 0, 2], [5, 0, 4], [5, 4, 4], [0, 4, 2],
], float)
_quads = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (1, 2, 6, 5), (0, 3, 7, 4)]
_wtris = []
for a, b, c, d in _quads:
    _wtris.append([a, b, c]); _wtris.append([a, c, d])
_wtris = np.array(_wtris, int)
wn, wt = acoustic_mesh.build_volume_mesh(_corners, _wtris, n_per_meter=6.0)
col_w = fu.make_column("box", diameter=0.5, depth=0.5, position=(2.5, 2.0, 0.0))
fu.sync_column_height(col_w, _corners)                 # usa z GLOBAL: span 0..4
cen = wn[wt].mean(axis=1)
occ = fu.occupancy(cen, [col_w])
above = int(np.count_nonzero(cen[occ][:, 2] > _ceiling_z(cen[occ][:, 0]) + 1e-9))
n2w, t2w, infow = fu.carve_mesh(wn, wt, [col_w])
V_rem = infow["V_removed_mesh"]
V_real = 0.5 * 0.5 * float(_ceiling_z(2.5))   # aire real en huella (techo local 3.0)
V_global = 0.5 * 0.5 * 4.0                     # si tallara hasta z_max global
print(f"    size_z columna = {col_w.size[2]:.2f} m (span sala 0..4)")
print(f"    tets removidos por ENCIMA del techo local = {above} de {int(occ.sum())}")
print(f"    V_removido = {V_rem:.3f}  |  aire real huella = {V_real:.3f}  |  prisma global = {V_global:.3f}")
check("columna sincronizada cubre toda la altura de sala (size_z = z_max global)",
      abs(col_w.size[2] - 4.0) < 1e-6, f"size_z={col_w.size[2]:.3f}")
check("NINGUN tet removido por encima del techo local (no talla aire inexistente)",
      above == 0, f"{above} de {int(occ.sum())} tets removidos por encima")
check("V removido ~ aire real en huella (NO el prisma global): es dibujo, no fisica",
      V_rem < 0.98 * V_global and 0.8 <= V_rem / V_real <= 1.35,
      f"V_rem={V_rem:.3f} (ratio real {V_rem/V_real:.3f}, global {V_rem/V_global:.3f})")

# ---------------------------------------------------------------------------
n_ok = sum(1 for _n, c, _d in results if c)
print(f"\n{n_ok}/{len(results)} tests OK")
if n_ok < len(results):
    raise SystemExit(1)
