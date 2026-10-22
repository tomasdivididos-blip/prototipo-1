"""
dba.py
======

Fase S5 del modelo de fuente exacto (ver `plan_modelo_fuente.md`): subs
enfrentados (DBA/CABS) sobre la base modal distribuida de `source_coupling.py`.

Configuracion CABS (Nielsen & Celestinos): un array de pared entera en el frente
(y=0) lanza una onda plana; un array en la pared opuesta (y=Ly) reproduce la
misma senal RETARDADA por Ly/c e INVERTIDA, absorbiendo la reflexion. En estado
estacionario a frecuencia f el drive trasero es

    v_r(f) = -v0 * exp(-i*omega*Ly/c)          (retardo Ly/c + inversion)

MECANISMO (prueba analitica). El acoplamiento de un modo axial (0,m,0) es
C_m ∝ v0 + v_r*(-1)^m  (el frente da face=+1, el trasero face=(-1)^m). Con el
drive de arriba, C_m ∝ 1 - exp(-i*omega*Ly/c)*(-1)^m. En la resonancia del modo,
k = k_m = m*pi/Ly  ->  omega*Ly/c = k*Ly = m*pi  ->  exp(-i m pi) = (-1)^m, y

    C_m(k_m) ∝ 1 - (-1)^m (-1)^m = 0.

El cero del numerador cancela el polo: el modo NO resuena. El campo pasa de
estacionario (resonante) a viajero (no resonante). Esa es la razon por la que
subs enfrentados funciona, y el modelo modal de hoy (fuente puntual) no la ve.

Modelo (a) SINK MANEJADO, implementado aca. El modelo (b) sink por impedancia
matcheada (Z=rho0*c) NO es perturbativo (beta ~ 1, pared totalmente absorbente),
asi que la Capa 0 de perturbacion no lo captura; CABS es un sistema manejado, no
un absorbente pasivo, asi que (a) es la representacion fisica correcta.
"""

from __future__ import annotations

import numpy as np
from typing import Callable

from source_coupling import RectModalBasis, WallPiston
from sources import RHO0, C0


def travel_delay(basis: RectModalBasis, axis: int = 1) -> float:
    """Tiempo de transito de la onda plana a lo largo del eje: L_axis / c."""
    return basis.dims[axis] / basis.c


def cabs_rear_gain(dims, axis: int = 1, *, rt60: float | None = None,
                   xi: float | None = None, c: float = C0, air: bool = True,
                   T: float = 20.0, RH: float = 50.0, P: float = 101325.0):
    """Ganancia G(f) del parlante trasero del CABS (Celestinos & Nielsen, JAES
    56(11) 2008, sec. 2.3 y Fig. 7).

    El frente de onda que llega a la pared trasera NO tiene amplitud 1: viene
    atenuado por el amortiguamiento de la sala y por la absorcion del aire sobre
    la distancia de viaje L=dims[axis]. Para cancelarlo, el trasero debe igualar
    ESA amplitud, no 1. Se modela

        G(f) = exp(-delta * L / c) * exp(-alpha_aire(f) * L)

    con delta la tasa de decaimiento (Np/s): delta = 3*ln(10)/RT60 si se da el
    RT60 efectivo (= T30 Schroeder), o delta = xi*omega_1 del primer axial si se
    da xi. Si no hay ni RT60 ni xi, el termino de amortiguamiento es 1 (solo
    aire). alpha_aire por ISO 9613-1.

    Devuelve un callable G(f) (float->float). Es real y <=1.
    """
    import acoustic_analysis as _aa
    L = float(dims[axis])
    if rt60 is not None and rt60 > 0:
        delta = 3.0 * np.log(10.0) / float(rt60)
    elif xi is not None and xi > 0:
        # omega del primer axial sobre el eje: k_1 = pi/L -> omega_1 = c*pi/L.
        omega_1 = c * np.pi / L
        delta = float(xi) * omega_1
    else:
        delta = 0.0
    g_damp = float(np.exp(-delta * L / c))

    def G_of_f(f: float) -> float:
        g = g_damp
        if air:
            a = _aa.air_absorption_alpha(float(f), T=T, RH=RH, P=P)
            g *= float(np.exp(-a * L))
        return g

    return G_of_f


def _as_gain_fn(rear_gain):
    """Normaliza rear_gain (float|callable|None) a un callable G(f)->float."""
    if rear_gain is None:
        return lambda f: 1.0
    if callable(rear_gain):
        return rear_gain
    g = float(rear_gain)
    return lambda f: g


def front_only_coupling(basis: RectModalBasis, axis: int = 1,
                        front_vn: complex = 1.0) -> np.ndarray:
    """CABS OFF: solo el array frontal de pared entera (C_n fijo)."""
    return basis.wall_piston_coupling(
        WallPiston(axis=axis, side="min", vn=front_vn))


def dba_coupling_fn(basis: RectModalBasis, axis: int = 1,
                    front_vn: complex = 1.0, delay: float | None = None,
                    invert: bool = True, rear_gain=1.0
                    ) -> Callable[[float], np.ndarray]:
    """CABS ON: devuelve C(f) con el frente + trasero manejado.

    delay=None -> Ly/c (retardo de transito). invert=True -> inversion de
    polaridad del trasero (el default de CABS). rear_gain -> ganancia G del
    trasero (float, callable G(f), o None=1.0); default 1.0 = comportamiento
    historico. Ver `cabs_rear_gain` para el G fisico (amortiguamiento + aire).
    """
    if delay is None:
        delay = travel_delay(basis, axis)
    sign = -1.0 if invert else 1.0
    front = WallPiston(axis=axis, side="min", vn=front_vn)
    C_front = basis.wall_piston_coupling(front)
    G = _as_gain_fn(rear_gain)

    def C_of_f(f: float) -> np.ndarray:
        omega = 2.0 * np.pi * f
        vr = sign * G(f) * front_vn * np.exp(-1j * omega * delay)
        rear = WallPiston(axis=axis, side="max", vn=vr)
        return C_front + basis.wall_piston_coupling(rear)

    return C_of_f


def array_naive_coupling_fn(basis: RectModalBasis, front: list, rear: list,
                            axis: int = 1, delay: float | None = None,
                            rear_gain=1.0) -> Callable[[float], np.ndarray]:
    """Drive de RETARDO naive para arrays de pistones front/rear (generaliza
    dba_coupling_fn a grillas): C(f) = Cf - G(f) e^{-i w tau} * Cr, con Cf/Cr los
    acoplamientos de las grillas (vn=1), tau el tiempo de tránsito y G la ganancia
    del trasero (default 1.0 = histórico)."""
    if delay is None:
        delay = travel_delay(basis, axis)
    Cf = coupling_matrix(basis, front).sum(axis=1)
    Cr = coupling_matrix(basis, rear).sum(axis=1)
    G = _as_gain_fn(rear_gain)

    def C_of_f(f: float) -> np.ndarray:
        return Cf - G(f) * np.exp(-1j * 2.0 * np.pi * f * delay) * Cr

    return C_of_f


def axial_resonance_coupling(basis: RectModalBasis, axis: int, mode_index: int,
                             front_vn: complex = 1.0) -> complex:
    """|C_m| del modo axial `mode_index` evaluado en SU resonancia, con el drive
    DBA. Debe ser ~0 (cancelacion polo-cero). Para el oraculo T1."""
    C_fn = dba_coupling_fn(basis, axis=axis, front_vn=front_vn)
    f_m = basis.freqs[mode_index]
    return complex(C_fn(f_m)[mode_index])


# ---------------------------------------------------------------------------
# Drive LS-optimo (Santillan): arrays de pistones + minimos cuadrados
# ---------------------------------------------------------------------------
def piston_wall_grid(basis: RectModalBasis, axis: int, side: str,
                     n_a: int, n_b: int, *, size: float = 0.1,
                     inset: float = 0.05) -> list:
    """Grilla de pistones cuadrados sobre una pared (layout de Santillan).

    n_a x n_b pistones sobre los dos ejes distintos de `axis`, con centros
    equiespaciados desde `inset` hasta L-`inset`. size = lado del piston [m].
    """
    a, b = tuple(x for x in (0, 1, 2) if x != axis)
    La, Lb = basis.dims[a], basis.dims[b]
    ca = np.linspace(inset, La - inset, n_a) if n_a > 1 else np.array([La / 2])
    cb = np.linspace(inset, Lb - inset, n_b) if n_b > 1 else np.array([Lb / 2])
    h = size / 2.0
    pistons = []
    for ua in ca:
        for ub in cb:
            span = (ua - h, ua + h, ub - h, ub + h)
            pistons.append(WallPiston(axis=axis, side=side, span=span, vn=1.0))
    return pistons


def coupling_matrix(basis: RectModalBasis, pistons: list) -> np.ndarray:
    """Matriz de acoplamiento (Nm, L): columna l = C_n del piston l con vn=1."""
    return np.column_stack([basis.wall_piston_coupling(p) for p in pistons])


def plane_wave_target(sensors, k: float, axis: int = 1) -> np.ndarray:
    """Onda plana viajera en +axis, amplitud unidad: d_m = exp(-i k y_m)."""
    pts = np.atleast_2d(np.asarray(sensors, dtype=float))
    return np.exp(-1j * k * pts[:, axis])


def ls_drive(basis: RectModalBasis, Cmat: np.ndarray, Phi_s: np.ndarray,
             sensors, f: float, *, axis: int = 1, xi: float = 0.03,
             reg: float = 0.0, rho0: float = RHO0):
    """Drive LS-optimo a la frecuencia f (metodo de Santillan, dominio de f).

    Minimiza ||Z q - d||^2 con Z_{m,l} = presion en sensor m por fuente l (vn=1),
    d = onda plana viajera objetivo. Devuelve (q, C_opt, E_LS) con:
      q      : (L,) fuerzas complejas optimas
      C_opt  : (Nm,) acoplamiento resultante = Cmat @ q
      E_LS   : ||Z q - d|| / ||d||   (error de minimos cuadrados normalizado)
    """
    omega = 2.0 * np.pi * f
    k = omega / basis.c
    denom = (basis.omega_n ** 2 - omega ** 2) + 2j * xi * basis.omega_n * omega
    denom = np.where(np.abs(denom) < 1e-30, 1e-30, denom)
    # Z = i w rho0 c^2 * Phi_s @ (Cmat / denom)
    Z = 1j * omega * rho0 * basis.c ** 2 * (Phi_s @ (Cmat / denom[:, None]))
    d = plane_wave_target(sensors, k, axis)
    if reg > 0.0:
        # Tikhonov con penalización RELATIVA al esfuerzo (reg escala con la
        # magnitud de Z, así el mismo reg vale a toda frecuencia): tamiza los
        # nulos profundos del LS sin regularizar (mal condicionado con pocos
        # subs). q = (Z^H Z + reg*<|diag|> I)^-1 Z^H d.
        ZhZ = Z.conj().T @ Z
        dd = float(np.mean(np.abs(np.diag(ZhZ))))
        if dd < 1e-30:                       # Z ~ 0 (p.ej. DC): sin drive
            q = np.zeros(Z.shape[1], dtype=complex)
        else:
            q = np.linalg.solve(ZhZ + reg * dd * np.eye(Z.shape[1]),
                                Z.conj().T @ d)
    else:
        q, *_ = np.linalg.lstsq(Z, d, rcond=None)
    resid = Z @ q - d
    E = float(np.linalg.norm(resid) / np.linalg.norm(d))
    C_opt = Cmat @ q
    return q, C_opt, E


def dba_ls_coupling_fn(basis: RectModalBasis, pistons: list, sensors, *,
                       axis: int = 1, xi: float = 0.03, reg: float = 0.0):
    """Devuelve C(f) usando el drive LS-optimo (refinamiento S5 de `dba`)."""
    Cmat = coupling_matrix(basis, pistons)
    Phi_s = basis.phi_matrix(sensors)

    def C_of_f(f: float) -> np.ndarray:
        _, C_opt, _ = ls_drive(basis, Cmat, Phi_s, sensors, f,
                               axis=axis, xi=xi, reg=reg)
        return C_opt

    return C_of_f


def ls_error_curve(basis: RectModalBasis, pistons: list, sensors, freqs, *,
                   axis: int = 1, xi: float = 0.03, reg: float = 0.0
                   ) -> np.ndarray:
    """E_LS(f) sobre un eje de frecuencias (para el cross-check vs Santillan)."""
    Cmat = coupling_matrix(basis, pistons)
    Phi_s = basis.phi_matrix(sensors)
    E = np.empty(len(freqs))
    for i, f in enumerate(freqs):
        _, _, E[i] = ls_drive(basis, Cmat, Phi_s, sensors, float(f),
                              axis=axis, xi=xi, reg=reg)
    return E


def santillan_global_eq(basis: RectModalBasis, pistons: list, sensors, freqs, *,
                        axis: int = 1, xi: float = 0.03, reg: float = 0.0,
                        model_delay: float | None = None, zone=None):
    """Ecualización GLOBAL de banda ancha (Santillán, JASA 110(4) 2001, §IV,
    ec. 10, Fig. 4): diseña un filtro FIR por fuente que ecualiza TODA la zona a
    lo largo de la banda, no un punto.

    Corre el LS-óptimo de Santillán `ls_drive` en cada frecuencia (q_l(f)),
    aplica un DELAY DE MODELADO δ_m (fase lineal, para que la respuesta impulsiva
    sea causal: el objetivo es una delta RETARDADA, §IV) y hace la IFFT de
    q_l(f)·e^{-iω δ_m} para obtener los coeficientes FIR h_l(n) por fuente.

    `freqs` DEBE ser una grilla uniforme [0, f_max] con Nf puntos (para la IFFT
    one-sided). `model_delay=None` -> tiempo de tránsito del plano de sensores
    sobre `axis`. `zone` (grilla de receptores) opcional: si se pasa, devuelve la
    planitud de la zona corregida (std_f de la media espacial) como chequeo.

    Devuelve dict: {freqs, Q (Nf,L drive), filters (L,N), fs, model_delay,
    E_ls (Nf), zone_flat (float|None)}.
    """
    freqs = np.asarray(freqs, dtype=float)
    Nf = len(freqs)
    Cmat = coupling_matrix(basis, pistons)
    Phi_s = basis.phi_matrix(sensors)
    Ln = len(pistons)
    Q = np.zeros((Nf, Ln), dtype=complex)
    E = np.zeros(Nf)
    for j, f in enumerate(freqs):
        q, _, e = ls_drive(basis, Cmat, Phi_s, sensors, float(f),
                           axis=axis, xi=xi, reg=reg)
        Q[j] = q
        E[j] = e
    # Delay de modelado: por default, el tránsito a lo largo del span de sensores.
    if model_delay is None:
        span = float(np.ptp(np.atleast_2d(np.asarray(sensors, float))[:, axis]))
        model_delay = span / basis.c
    omega = 2.0 * np.pi * freqs
    Qd = Q * np.exp(-1j * omega * model_delay)[:, None]
    Qd[0] = 0.0                                   # sin DC (evita offset)
    # FIR por fuente: IFFT one-sided. N muestras = 2*(Nf-1), fs = 2*f_max.
    n_time = 2 * (Nf - 1)
    filters = np.zeros((Ln, n_time), dtype=float)
    for l in range(Ln):
        filters[l] = np.fft.irfft(Qd[:, l], n=n_time)
    fs = 2.0 * float(freqs[-1])
    zone_flat = None
    if zone is not None:
        zone = np.asarray(zone, dtype=float)
        Lbar = np.empty(Nf)
        for j, f in enumerate(freqs):
            if f <= 0:
                Lbar[j] = np.nan
                continue
            C_opt = Cmat @ Q[j]
            p = np.abs(basis.pressure_field(zone, float(f), C_opt, xi=xi))
            Lbar[j] = 20.0 * np.log10(np.mean(p) + 1e-30)
        zone_flat = float(np.nanstd(Lbar))
    return {"freqs": freqs, "Q": Q, "filters": filters, "fs": fs,
            "model_delay": float(model_delay), "E_ls": E, "zone_flat": zone_flat}


def impulse_response(basis: RectModalBasis, receiver, coupling, *,
                     fmax: float = 200.0, n_freq: int = 4096,
                     xi: float = 0.03):
    """Respuesta impulsiva por IFFT de la FRF sobre [0, fmax].

    `coupling` puede ser un vector C_n fijo (CABS off) o un callable C(f) (DBA).
    Devuelve (t, h) con h real. Sirve para medir el colapso del decay.
    """
    freqs = np.linspace(0.0, fmax, n_freq)
    if callable(coupling):
        H = basis.frf_dispersive(receiver, freqs, coupling, xi=xi)
    else:
        H = basis.frf(receiver, freqs, coupling, xi=xi)
    H[0] = 0.0                                   # sin DC
    h = np.fft.irfft(H, n=2 * (n_freq - 1))
    fs = 2.0 * fmax
    t = np.arange(h.size) / fs
    return t, h


def _zone_grid(dims, axis: int, n_a=5, n_b=4, n_c=5, margin=0.5):
    """Grilla de receptores en la zona de escucha: descuenta `margin` de las
    dos paredes perpendiculares a `axis` (donde están los arrays) y de bordes."""
    los = [margin, margin, margin]
    his = [d - margin for d in dims]
    ns = [n_a, n_b, n_c]
    axes = [np.linspace(los[k], his[k], ns[k]) if his[k] > los[k]
            else np.array([dims[k] / 2]) for k in range(3)]
    return np.array([[x, y, z] for x in axes[0] for y in axes[1] for z in axes[2]])


def _t_decay(t, sch, level_db=-15.0):
    i = int(np.argmax(sch <= level_db))
    return float(t[i]) if sch[i] <= level_db else float(t[-1])


def alias_fmax(dims, axis: int, n_a: int, n_b: int, c: float = C0,
               inset: float = 0.05, rt60: float | None = None,
               delta_e: float | None = None) -> float:
    """Frecuencia máxima de ecualización f_max = c/d − Δe (CABS, Celestinos &
    Nielsen JAES 56(11) 2008, sec. 2.1), con d el mayor espaciado entre subs
    adyacentes en los dos ejes transversales a `axis`. Por encima de f_max el
    array no puede sintetizar la onda plana (aliasing espacial) y el DBA deja de
    servir. Devuelve inf si hay 1 sub por eje.

    Δe DEPENDE DEL AMORTIGUAMIENTO. La tesis de Celestinos (2007, Paper D §3.1,
    p.83) y el paper JAES lo dejan explícitamente como "una constante que depende
    del amortiguamiento de la sala, aproximable del tiempo de reverberación",
    SIN fórmula cerrada. APROXIMACIÓN documentada acá: Δe = δ/π = 3·ln10/(π·RT60)
    (el ancho de banda de media potencia modal, en Hz), que achica la banda útil
    cuando la sala es más amortiguada. `delta_e` explícito la fija a mano.
    Default (ambos None) -> Δe=0 = comportamiento histórico (solo c/d).
    """
    a, b = tuple(x for x in (0, 1, 2) if x != axis)
    ds = []
    for L, n in ((dims[a], n_a), (dims[b], n_b)):
        if n > 1:
            ds.append((L - 2 * inset) / (n - 1))
    if not ds:
        return float("inf")
    f_alias = c / max(ds)
    if delta_e is not None:
        de = float(delta_e)
    elif rt60 is not None and rt60 > 0:
        de = 3.0 * np.log(10.0) / (np.pi * float(rt60))
    else:
        de = 0.0
    return float(max(f_alias - de, 0.0))


def compute_dba(dims, receiver, *, axis: int = 1, n_x: int = 4, n_z: int = 4,
                drive: str = "ls", xi: float = 0.03, fmin: float = 20.0,
                fmax: float = 200.0, n_freq: int = 220, reg: float = 0.005,
                c: float = C0, rear_gain=1.0, rt60=None) -> dict:
    """Análisis DBA/CABS para una sala rectangular (motor headless de la
    herramienta de GUI). Compara CABS off (array frontal solo) vs on (front +
    rear con el drive elegido).

    Las métricas (planitud espectral, varianza espacial) se miden en la BANDA
    VÁLIDA [fmin, min(fmax, f_max=c/d−Δe)]: arriba de f_max hay aliasing espacial
    y el DBA no aplica, así que promediar ahí ensuciaría el número. El drive LS se
    regulariza (reg) para no crear nulos profundos. drive: "ls" | "naive".

    `rear_gain` (float|callable, default 1.0): ganancia G del trasero del drive
    naive (ver `cabs_rear_gain`). `rt60` (opcional): aplica el término Δe a f_max
    (CABS §2.1); None = Δe=0 = histórico. Ambos defaults = comportamiento previo.
    """
    dims = tuple(float(x) for x in dims)
    receiver = np.asarray(receiver, dtype=float)
    n_max = int(2.0 * fmax * max(dims) / c) + 3
    basis = RectModalBasis(dims, fmax=fmax * 1.3, n_max=n_max, c=c)
    front = piston_wall_grid(basis, axis, "min", n_x, n_z)
    rear = piston_wall_grid(basis, axis, "max", n_x, n_z)
    zone = _zone_grid(dims, axis)

    C_before = coupling_matrix(basis, front).sum(axis=1)
    if drive == "naive":
        C_after = array_naive_coupling_fn(basis, front, rear, axis,
                                          rear_gain=rear_gain)
    else:
        C_after = dba_ls_coupling_fn(basis, front + rear, zone, axis=axis,
                                     xi=xi, reg=reg)

    f_max = alias_fmax(dims, axis, n_x, n_z, c=c, rt60=rt60)
    band_hi = min(fmax, f_max)

    fa = np.linspace(fmin, fmax, n_freq)
    Hb = basis.frf(receiver, fa, C_before, xi=xi)
    Ha = basis.frf_dispersive(receiver, fa, C_after, xi=xi)
    Hb_db = 20.0 * np.log10(np.abs(Hb) + 1e-12)
    Ha_db = 20.0 * np.log10(np.abs(Ha) + 1e-12)

    # planitud espectral SOLO en la banda válida
    inb = (fa >= fmin) & (fa <= band_hi)
    if np.count_nonzero(inb) < 4:            # banda válida muy chica
        inb = fa <= max(band_hi, fa[3])
    flat_before = float(np.std(Hb_db[inb]))
    flat_after = float(np.std(Ha_db[inb]))

    # varianza espacial en la banda válida
    sb, sa = [], []
    for f in np.linspace(max(fmin, 25.0), band_hi, 18):
        pb = np.abs(basis.pressure_field(zone, f, C_before, xi=xi))
        Cf = C_after(f) if callable(C_after) else C_after
        pa = np.abs(basis.pressure_field(zone, f, Cf, xi=xi))
        sb.append(np.std(20.0 * np.log10(pb / pb.mean())))
        sa.append(np.std(20.0 * np.log10(pa / pa.mean())))

    return {
        "freq": fa, "Hb_db": Hb_db, "Ha_db": Ha_db,
        "flat_before": flat_before, "flat_after": flat_after,
        "spatial_before": float(np.mean(sb)), "spatial_after": float(np.mean(sa)),
        "f_max": f_max, "band_hi": float(band_hi),
        "n_modes": basis.n_modes,
        "n_front": len(front), "n_rear": len(rear),
    }


def piston_center(piston: WallPiston, dims) -> tuple:
    """Centro 3D del pistón sobre su pared (coordenadas [0,L])."""
    d = piston.axis
    a, b = piston.other_axes()
    a0, a1, b0, b1 = piston.resolved_span(dims)
    pos = [0.0, 0.0, 0.0]
    pos[d] = 0.0 if piston.side == "min" else float(dims[d])
    pos[a] = 0.5 * (a0 + a1)
    pos[b] = 0.5 * (b0 + b1)
    return tuple(pos)


def build_dba_sources(dims, *, axis: int = 1, n_x: int = 4, n_z: int = 4,
                      drive: str = "ls", xi: float = 0.03, fmin: float = 20.0,
                      fmax: float = 180.0, reg: float = 0.005,
                      inset: float = 0.06, c: float = C0, rear_gain=1.0) -> list:
    """Materializa un preset DBA como fuentes PUNTUALES (monopolos) para inyectar
    en la lista de fuentes del panel. Devuelve specs dict en coordenadas [0,L]:
      {pos, label, Q, delay_s, polarity, response}

    - naive: frente en fase (Q=1); trasero Q=1, delay=L/c, polaridad=-1. Mapea
      EXACTO al campo de OmniSource (delay + polaridad).
    - ls: se resuelve q_l(f) para TODAS las fuentes (Santillán) y se hornea como
      curva de respuesta por fuente (drive dependiente de f). Bajo Schroeder el
      pistón ≈ monopolo (ka≪1), así que el punto reproduce el DBA analítico.

    Los centros se meten `inset` adentro de la pared (el sub está en la pared)."""
    from sources import SourceResponse
    dims = tuple(float(x) for x in dims)
    n_max = int(2.0 * fmax * max(dims) / c) + 3
    basis = RectModalBasis(dims, fmax=fmax * 1.3, n_max=n_max, c=c)
    front = piston_wall_grid(basis, axis, "min", n_x, n_z)
    rear = piston_wall_grid(basis, axis, "max", n_x, n_z)
    pistons = front + rear
    L = dims[axis]

    def _center(p):
        pos = list(piston_center(p, dims))
        pos[p.axis] = inset if p.side == "min" else L - inset
        return tuple(pos)

    def _lbl(l):
        return (f"DBA-F{l}" if l < len(front) else f"DBA-R{l - len(front)}")

    def _facing(p):
        """(orientation_deg | None, pitch_deg) del bafle mirando HACIA ADENTRO
        del recinto. El frente (side='min') mira en +eje; el trasero
        (side='max'), en -eje. Para el eje Z (piso/techo) el frente mira con la
        inclinacion (pitch) hacia arriba/abajo, no con el azimut."""
        inward = (p.side == "min")
        if p.axis == 0:      # X
            return (0.0 if inward else 180.0, 0.0)
        if p.axis == 1:      # Y
            return (90.0 if inward else 270.0, 0.0)
        return (90.0, 90.0 if inward else -90.0)   # Z: por pitch

    specs = []
    if drive == "naive":
        delay = L / c
        # Ganancia G del trasero (amortiguamiento + aire). Se hornea como Q
        # escalar (el termino de amortiguamiento domina y es ~plano en la banda).
        Gfn = _as_gain_fn(rear_gain)
        g_rear = complex(Gfn(0.5 * (fmin + fmax)))
        for i, p in enumerate(front):
            ori, pit = _facing(p)
            specs.append(dict(pos=_center(p), label=f"DBA-F{i}", Q=1.0 + 0j,
                              delay_s=0.0, polarity=1, response=None,
                              orientation=ori, pitch=pit))
        for i, p in enumerate(rear):
            ori, pit = _facing(p)
            specs.append(dict(pos=_center(p), label=f"DBA-R{i}", Q=g_rear,
                              delay_s=delay, polarity=-1, response=None,
                              orientation=ori, pitch=pit))
    else:
        zone = _zone_grid(dims, axis)
        Cmat = coupling_matrix(basis, pistons)
        Phi = basis.phi_matrix(zone)
        fa = np.linspace(fmin, fmax, 60)
        Q = np.zeros((len(fa), len(pistons)), dtype=complex)
        for j, f in enumerate(fa):
            q, _, _ = ls_drive(basis, Cmat, Phi, zone, float(f),
                               axis=axis, xi=xi, reg=reg)
            Q[j] = q
        norm = float(np.max(np.abs(Q))) or 1.0
        Qn = Q / norm
        for l, p in enumerate(pistons):
            g = Qn[:, l]
            gain_db = 20.0 * np.log10(np.maximum(np.abs(g), 1e-6))
            phase = np.unwrap(np.angle(g))
            resp = SourceResponse(fa, gain_db, phase, name=_lbl(l), anchor="")
            ori, pit = _facing(p)
            specs.append(dict(pos=_center(p), label=_lbl(l), Q=1.0 + 0j,
                              delay_s=0.0, polarity=1, response=resp,
                              orientation=ori, pitch=pit))
    return specs


def schroeder_decay_db(h: np.ndarray) -> np.ndarray:
    """Curva de decaimiento de Schroeder (integral invertida de energia) en dB,
    normalizada a 0 dB en t=0."""
    energy = h[::-1] ** 2
    sch = np.cumsum(energy)[::-1]
    sch = sch / np.max(sch)
    return 10.0 * np.log10(np.maximum(sch, 1e-20))


if __name__ == "__main__":
    dims = (7.8, 4.1, 2.8)
    basis = RectModalBasis(dims, fmax=180.0)
    print(f"sala {dims}: {basis.n_modes} modos hasta 180 Hz")

    # Cancelacion polo-cero en cada axial-y.
    print("  |C_m| en resonancia (DBA on) para axiales-y:")
    for i, m in enumerate(basis.modes):
        if m[0] == 0 and m[2] == 0 and m[1] >= 1:
            Cm = abs(axial_resonance_coupling(basis, 1, i))
            print(f"    modo {m}  f={basis.freqs[i]:6.2f} Hz  |C_m(res)|={Cm:.2e}")
