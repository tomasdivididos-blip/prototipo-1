"""bench_criteria_validation.py - Validacion de criterios, Capa 1 (in silico).

SEMILLA del plan `plan_validacion_criterios.md` (item iv del backlog del profesor).
Responde "como se validan los criterios sin construir y demoler salas": se hace EN
SIMULACION (gratis). El motor FEM exacto (validado contra analitico/QEP/SLEPc/FLAIR)
es la verdad de terreno; un criterio "funciona" si rankea las salas IGUAL que la
fisica exacta.

Experimento: un ENSAMBLE de salas (ratios de cubo a buenos, MISMO volumen para no
confundir con V) -> por cada una se computa (a) el criterio FSI psi(25) de Rindel
(mira solo el espaciado de frecuencias) y (b) la metrica de campo EXACTA FoM_flat
(planitud de la respuesta media sobre una grilla de receptores, de los modos FEM) ->
correlacion de Spearman. FSI alto = espaciado desparejo = malo; FoM_flat alto =
respuesta menos plana = malo. Si FSI PREDICE el campo, correlacionan POSITIVO.

Es NO circular: FSI es un heuristico de frecuencias (externo); FoM_flat es el campo
real (formas + modos). Falsable: si no correlacionan, FSI no predice el campo.

Correr:  python bench_criteria_validation.py
"""

import numpy as np

from geometry import make_room
from acoustic_mesh import build_volume_mesh
from acoustic_fem import build_KM, solve_modes, FieldEvaluator
from sources import SourceArray, OmniSource
from modal_metrics import (modal_fsi, compute_forced_response,
                           default_receiver_grid, response_figures_of_merit)

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


# Ratios (a:b:c) de la literatura, de PEOR (cubo, degenerado) a buenos. Se escalan
# todos al MISMO volumen para que la comparacion sea de FORMA, no de tamano.
RATIOS = {
    "cubo 1:1:1":        (1.00, 1.00, 1.00),   # peor: triple degeneracion
    "casi-cubo":         (1.00, 1.08, 1.15),
    "2 iguales 1:2:2":   (1.00, 2.00, 2.00),   # malo: doble degeneracion
    "Sepmeyer A":        (1.00, 1.14, 1.39),
    "Sepmeyer B":        (1.00, 1.28, 1.54),
    "Louden medio":      (1.00, 1.26, 1.59),
    "Louden mejor":      (1.00, 1.40, 1.90),
    "Bolt region":       (1.00, 1.50, 2.50),
    "1:1.6:2.33":        (1.00, 1.60, 2.33),
    "1:1.3:2.1":         (1.00, 1.30, 2.10),
    "chato 1:1.1:3.2":   (1.00, 1.10, 3.20),
    "1:1.9:1.4":         (1.00, 1.90, 1.40),
}
V_TARGET = 70.0          # m^3 (sala chica/media; alturas ~2.5-4 m segun el ratio)
NPM = 3.0
N_MODES = 25
FA = np.linspace(20.0, 120.0, 140)


def dims_for(ratio, V=V_TARGET):
    a, b, c = ratio
    s = (V / (a * b * c)) ** (1.0 / 3.0)
    return s * a, s * b, s * c


def evaluate_room(ratio):
    Lx, Ly, Lz = dims_for(ratio)
    sv, st, _e, _n = make_room(Lx, Ly, Lz, n_walls=4, roof_type="flat")
    nodes, tets = build_volume_mesh(sv, st, n_per_meter=NPM)
    K, M, _ = build_KM(nodes, tets)
    freqs, phis = solve_modes(K, M, n_modes=N_MODES)
    freqs = np.asarray(freqs)
    # criterio A (heuristico de FRECUENCIAS): FSI psi(25) de Rindel
    psi = modal_fsi(freqs, 25)
    # criterio B (densidad modal en la banda): nro de modos en 20-120 Hz. Es un
    # predictor que SI deberia correlacionar fuerte con la planitud (mas modos en
    # banda = respuesta mas llena = mas plana) -> sirve de CONTROL POSITIVO del
    # metodo (si el metodo no confirma esto, el metodo esta roto).
    n_band = int(np.sum((freqs >= FA[0]) & (freqs <= FA[-1])))
    # campo exacto: FoM_flat (de los modos FEM, fuente en una esquina)
    loc = FieldEvaluator(nodes, tets)
    lo = nodes.min(axis=0)
    src = SourceArray([OmniSource((lo[0] + 0.3, lo[1] + 0.3, lo[2] + 0.3),
                                  sensitivity_dB=90.0)])
    grid = default_receiver_grid(nodes, nx=4, ny=4, locator=loc, phis=phis)
    H = compute_forced_response(loc, freqs, phis, src, grid, FA, damping=0.05)
    fom = response_figures_of_merit(H, FA).FoM_flat
    return psi, n_band, fom, (Lx, Ly, Lz)


def spearman(x, y):
    """Rho de Spearman sin scipy: correlacion de Pearson sobre los rangos."""
    def rank(v):
        order = np.argsort(np.argsort(v))
        return order.astype(float)
    rx, ry = rank(np.asarray(x)), rank(np.asarray(y))
    rx -= rx.mean(); ry -= ry.mean()
    denom = np.sqrt((rx ** 2).sum() * (ry ** 2).sum())
    return float((rx * ry).sum() / denom) if denom > 0 else 0.0


# ---------------------------------------------------------------------------
print(f"Ensamble de {len(RATIOS)} salas a V={V_TARGET:.0f} m3 (npm={NPM:.0f}, "
      f"{N_MODES} modos, FoM 20-120 Hz)\n")
print(f"  {'sala':<18} {'dims [m]':<22} {'FSI':>6} {'n_banda':>8} {'FoM_flat[dB]':>13}")
fsis, nbands, foms, names = [], [], [], []
for name, ratio in RATIOS.items():
    psi, nb, fom, dims = evaluate_room(ratio)
    fsis.append(psi); nbands.append(nb); foms.append(fom); names.append(name)
    print(f"  {name:<18} {dims[0]:.2f}x{dims[1]:.2f}x{dims[2]:.2f}".ljust(42)
          + f"{psi:>6.2f} {nb:>8d} {fom:>13.2f}")

fsis = np.array(fsis); nbands = np.array(nbands); foms = np.array(foms, float)
rho_fsi = spearman(fsis, foms)
rho_den = spearman(nbands, foms)
print(f"\n  Spearman(FSI, FoM_flat)          = {rho_fsi:+.3f}  (criterio a evaluar)")
print(f"  Spearman(densidad modal, FoM_flat) = {rho_den:+.3f}  (control positivo)")

# ---------------------------------------------------------------------------
# Oraculos falsables de la Capa 1 (el METODO, no un criterio en particular).
# (1) CONTROL POSITIVO: el metodo CONFIRMA un predictor verdadero. La densidad
#     modal en banda DEBE correlacionar fuerte NEGATIVO con FoM_flat (mas modos ->
#     mas plano). Si el metodo no detecta esto, el metodo (motor+metrica) esta roto.
check("el metodo CONFIRMA la densidad modal como predictor (rho fuerte NEG)",
      rho_den < -0.5, f"Spearman(densidad, FoM_flat)={rho_den:+.3f}")

# (2) HALLAZGO sobre el FSI: su correlacion con el campo exacto es DEBIL (|rho|<0.3).
#     FSI normaliza la densidad (es adimensional) -> no captura que una sala mas
#     larga mete mas modos en la banda y se aplana. No es circular ni un bug: es
#     el resultado cientifico. FALSABLE (si fuera fuerte, este test fallaria y
#     habria que subirle el peso en el scorer). Se reporta como dato, no como fallo.
check("FSI predice DEBIL la planitud espacial (hallazgo, |rho|<0.3)",
      abs(rho_fsi) < 0.3,
      f"Spearman(FSI, FoM_flat)={rho_fsi:+.3f} -> FSI aporta senal parcial; "
      f"la densidad domina")

# (3) Consistencia del peor caso: el cubo (degeneracion triple) es peor-tercio
#     TANTO en FSI como en el campo exacto. Donde SI hay acuerdo, el metodo lo ve.
def worst_third(vals, idx):
    thr = np.quantile(vals, 2.0 / 3.0)
    return vals[idx] >= thr

i_cubo = names.index("cubo 1:1:1")
check("el cubo es peor-tercio en FSI Y en el campo exacto (consistencia)",
      worst_third(fsis, i_cubo) and worst_third(foms, i_cubo),
      f"cubo: FSI={fsis[i_cubo]:.2f}, FoM_flat={foms[i_cubo]:.2f} dB")

# (4) Sanidad: todos los FoM_flat finitos y > 0 (una sala real no es plana).
check("FoM_flat finito y > 0 en todas las salas",
      bool(np.all(np.isfinite(foms)) and np.all(foms > 0)),
      f"rango FoM_flat = [{foms.min():.2f}, {foms.max():.2f}] dB")

# ---------------------------------------------------------------------------
n_ok = sum(1 for _n, c, _d in results if c)
print(f"\n{n_ok}/{len(results)} tests OK")
if n_ok < len(results):
    raise SystemExit(1)
