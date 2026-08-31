"""
frd.py
======

Lectura de archivos FRD (Frequency Response Data), el formato nativo de
VituixCAD / REW para respuesta de fuentes. Fase 1 del plan_fuentes.

Formato tipico (whitespace, coma o tab; 2 o 3 columnas):

    * comentarios opcionales con * (tambien # o ;)
    freq_hz   spl_db   phase_deg
    20.00     78.3     -145.2
    20.50     78.6     -144.8
    ...

El parser es tolerante: ignora comentarios y lineas en blanco, acepta
coma/espacio/tab como separador, ordena por frecuencia y deduplica.

La conversion SPL+fase -> ganancia g(f) NO vive aca; vive en
sources.SourceResponse.from_frd (necesita el Q baseline de la fuente y el
modo de anclaje). Aca solo se lee el archivo a arrays crudos.
"""

from __future__ import annotations

import numpy as np
from typing import Tuple, Optional


def load_frd(path: str) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]:
    """Lee un .frd -> (freq_hz, spl_db, phase_deg | None).

    - Comentarios: lineas que empiezan con '*', '#' o ';' (tras strip).
    - Separador: cualquier mezcla de coma / espacio / tab.
    - 2 columnas -> phase_deg = None.  3+ columnas -> usa la 3a como fase.
    - Ordena por frecuencia ascendente y deduplica frecuencias repetidas
      (se queda con la primera ocurrencia).

    Lanza ValueError si no encuentra al menos 2 puntos validos.
    """
    freqs, spls, phases = [], [], []
    has_phase = True
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line[0] in "*#;":
                continue
            parts = line.replace(",", " ").split()
            if len(parts) < 2:
                continue
            try:
                f = float(parts[0]); s = float(parts[1])
            except ValueError:
                continue                      # encabezado de texto, etc.
            freqs.append(f); spls.append(s)
            if len(parts) >= 3:
                try:
                    phases.append(float(parts[2]))
                except ValueError:
                    phases.append(0.0); has_phase = False
            else:
                has_phase = False

    if len(freqs) < 2:
        raise ValueError(
            f"FRD '{path}': se necesitan >=2 puntos validos, se leyeron {len(freqs)}.")

    freq = np.asarray(freqs, dtype=float)
    spl = np.asarray(spls, dtype=float)
    phase = np.asarray(phases, dtype=float) if (has_phase and len(phases) == len(freqs)) else None

    # Ordenar y deduplicar por frecuencia.
    order = np.argsort(freq, kind="stable")
    freq, spl = freq[order], spl[order]
    if phase is not None:
        phase = phase[order]
    keep = np.concatenate([[True], np.diff(freq) > 0])
    freq, spl = freq[keep], spl[keep]
    if phase is not None:
        phase = phase[keep]
    return freq, spl, phase


_TRF_MAGIC = b"JACKREF!"
_TRF_NBINS_OFFSET = 0x2B4     # int32: cantidad de bins de frecuencia
_TRF_DIR_OFFSET = 0x2B8       # 5 x int32: offsets de los arrays de datos


def load_trf(path: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Lee un .trf binario (traza de transfer function dual-channel, magic
    ``JACKREF!``) -> (freq_hz, mag_db, phase_deg, coherence).

    Formato (ingenieria inversa, 5 Jul 2026, sobre trazas Focal_L/R.trf):
      - Header de campos fijos (nombre de traza, mic, interfaz, ventana,
        promediado). En ``0x2B4`` vive ``n_bins`` (int32 LE) y en ``0x2B8``
        un directorio de 5 offsets (int32 LE) a los arrays:
          [0] frecuencias   float32 x n   (eje MTW: fino abajo, grueso arriba)
          [1] magnitud [dB] float64 x n   (TF dual-channel: dB RELATIVOS ~0)
          [2] fase [rad]    float64 x n   (wrapped +-pi)
          [3] fase alt [rad] float64 x n  (segundo buffer; no se usa)
          [4] coherencia    float64 x n   (0..1)
      - El bloque grande entre header y directorio (espectros/IR crudos del
        promediador) se ignora.

    La magnitud es la de una TF (0 dB = misma señal en ambos canales), NO un
    SPL absoluto como el FRD: al construir la SourceResponse conviene anclaje
    "relative". La fase se devuelve en GRADOS por consistencia con load_frd.

    Valida el layout (offsets crecientes, tamaños exactos, eje monotono) y
    lanza ValueError con mensaje claro si el archivo no coincide.
    """
    import struct
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw[:8] != _TRF_MAGIC:
        raise ValueError(
            f"TRF '{path}': firma desconocida {raw[:8]!r} (se esperaba "
            f"{_TRF_MAGIC!r}). ¿Es un .trf de transfer function?")
    if len(raw) < _TRF_DIR_OFFSET + 20:
        raise ValueError(f"TRF '{path}': archivo truncado ({len(raw)} bytes).")

    n = struct.unpack_from("<i", raw, _TRF_NBINS_OFFSET)[0]
    offs = struct.unpack_from("<5i", raw, _TRF_DIR_OFFSET)
    layout_ok = (
        8 <= n <= 10**6
        and all(offs[i] < offs[i + 1] for i in range(4))
        and offs[1] - offs[0] == 4 * n            # freq: float32
        and all(offs[i + 1] - offs[i] == 8 * n for i in (1, 2, 3))  # float64
        and offs[4] + 8 * n <= len(raw)
    )
    if not layout_ok:
        raise ValueError(
            f"TRF '{path}': layout no reconocido (n={n}, offsets={offs}). "
            f"El parser conoce el formato de trazas guardadas; si el archivo "
            f"viene de otra version del software puede haber cambiado.")

    freq = np.frombuffer(raw, "<f4", count=n, offset=offs[0]).astype(float)
    mag = np.frombuffer(raw, "<f8", count=n, offset=offs[1]).astype(float)
    phase = np.frombuffer(raw, "<f8", count=n, offset=offs[2]).astype(float)
    coh = np.frombuffer(raw, "<f8", count=n, offset=offs[3 + 1]).astype(float)

    if not np.all(np.diff(freq) > 0):
        raise ValueError(f"TRF '{path}': eje de frecuencias no monotono.")

    # Descartar DC (f=0: magnitud -inf) y cualquier bin no-finito.
    keep = (freq > 0) & np.isfinite(mag) & np.isfinite(phase) & np.isfinite(coh)
    if keep.sum() < 2:
        raise ValueError(f"TRF '{path}': <2 bins validos tras filtrar DC/NaN.")
    freq, mag, phase, coh = freq[keep], mag[keep], phase[keep], coh[keep]
    return freq, mag, np.degrees(phase), np.clip(coh, 0.0, 1.0)


def minimum_phase(freq: np.ndarray, spl_db: np.ndarray) -> np.ndarray:
    """Fase minima [rad] sintetizada de la magnitud, para FRD sin columna de fase.

    Usa la relacion de Hilbert: para un sistema de fase minima,
        phase(ω) = -H{ ln|H(ω)| },
    con H el transformador de Hilbert. Se resamplea la log-magnitud sobre una
    grilla LINEAL en frecuencia (requisito del Hilbert discreto), se calcula la
    fase, y se devuelve interpolada de vuelta en `freq`.

    Aproximada cerca de los bordes de banda (el Hilbert asume cobertura
    infinita). Es una opcion, no el default — preferir la fase medida si existe.
    Convencion de signo e^{+iωt}: validar con un sistema conocido (test del
    pasa-altos de 1 polo en bench_frd.py).
    """
    from scipy.signal import hilbert
    f = np.asarray(freq, dtype=float)
    logmag = np.log(np.maximum(10.0 ** (np.asarray(spl_db, dtype=float) / 20.0), 1e-12))
    n = max(1024, 2 * len(f))
    f_uni = np.linspace(f[0], f[-1], n)
    lm_uni = np.interp(f_uni, f, logmag)
    # Reflect-pad (espejo a ambos lados) antes del Hilbert: mitiga el error de
    # wrap periodico en los bordes de banda (~2x mejor que sin padding).
    ext = np.concatenate([lm_uni[::-1], lm_uni, lm_uni[::-1]])
    # phase = -Im{ analytic(logmag) }  (signo validado con el oraculo del HP).
    ph_uni = -np.imag(hilbert(ext))[n:2 * n]
    return np.interp(f, f_uni, ph_uni)


# ---------------------------------------------------------------------------
# CLF (Common Loudspeaker Format) — lector de la RESPUESTA EN EJE
# ---------------------------------------------------------------------------
# Formato binario CF2 (1/3 de octava, 5°) / CF1 (octava, 10°). Es un binario
# COMPILADO, no encriptado (se leen strings de fabricante/modelo y arrays de
# float32), reverseado sobre 3 archivos QSC exportados por EASE SpeakerLab
# (v2.0c): q_spk_acc_2t / acs_4t / acs_6t.
#
# Lo que este lector extrae es SOLO la respuesta en eje (sensibilidad SPL vs
# frecuencia), que es lo único físicamente relevante para el solver modal bajo
# Schroeder: ahí las fuentes son omnidireccionales, así que el globo de
# directividad del CLF no moldea el campo. La directividad se descarta con
# fundamento (ver notas: pedido del profesor + sutileza física).
#
# Layout hallado (validado contra el CLF Viewer, ver bench_clf.py):
#   - On-axis = 27 x float32 LE en el byte 4764, en dB SPL @ 1W/1m.
#   - Precedido por la tensión de referencia 2.83 V (=2.828 Vrms; 2.83²/8Ω=1W)
#     repetida -> se usa como ANCLA robusta si el offset fijo no valida.
#   - Frecuencias IMPLÍCITAS: centros ISO 1/3 de octava 50 Hz .. 20 kHz (27),
#     no están en el archivo (son estándar del formato). El AC-C2T reproduce
#     EXACTO los 27 valores del viewer (error 0.0).
#
# Ref. formato: CLF Group (clfgroup.org). El CF2/CF1 no publica el layout
# binario; esto es ingeniería inversa validada por medición del propio viewer.
_CLF_ONAXIS_OFFSET = 4764          # byte del array on-axis (v2.0c EASE export)
_CLF_NBANDS = 27                   # 1/3 octava, 50 Hz .. 20 kHz
_CLF_REF_VOLTAGE = 2.83            # V (2.828 Vrms) -> ancla de fallback
# Centros ISO 1/3 de octava (R40 preferidas), 50 Hz .. 20 kHz.
CLF_THIRD_OCTAVE_HZ = np.array([
    50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800, 1000, 1250,
    1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000, 20000,
], dtype=float)


def _clf_onaxis_plausible(spl: np.ndarray) -> bool:
    """True si un candidato de 27 valores parece una respuesta en eje real:
    finitos, en rango SPL físico y suaves (sin saltos > 20 dB entre bandas)."""
    if spl.shape[0] != _CLF_NBANDS or not np.all(np.isfinite(spl)):
        return False
    if spl.min() < 20.0 or spl.max() > 150.0:
        return False
    return bool(np.max(np.abs(np.diff(spl))) < 20.0)


def _find_clf_onaxis(data: bytes) -> np.ndarray:
    """Ubica los 27 float32 de la respuesta en eje. Primero el offset fijo
    (v2.0c); si no valida, ancla en la corrida de tensión de referencia 2.83 V.
    Lanza ValueError si no encuentra un candidato plausible."""
    N = _CLF_NBANDS

    def _read(off):
        if off < 0 or off + 4 * N > len(data):
            return None
        return np.frombuffer(data[off:off + 4 * N], dtype="<f4").astype(float)

    # 1) offset fijo validado
    spl = _read(_CLF_ONAXIS_OFFSET)
    if spl is not None and _clf_onaxis_plausible(spl):
        return spl

    # 2) ancla: corrida de >=3 float32 ~ tensión de referencia (2..4 V), y luego
    #    los primeros 27 valores plausibles que aparezcan (saltando ceros).
    f32 = np.frombuffer(data[:len(data) // 4 * 4], dtype="<f4")
    is_ref = np.isfinite(f32) & (f32 > 2.0) & (f32 < 4.0)
    i = 0
    while i < len(f32) - N:
        if is_ref[i] and is_ref[i + 1] and is_ref[i + 2]:
            j = i + 3
            while j < len(f32) - N and abs(f32[j]) < 1e-6:   # saltar ceros
                j += 1
            cand = f32[j:j + N].astype(float)
            if _clf_onaxis_plausible(cand):
                return cand
            i = j
        i += 1
    raise ValueError(
        "CLF: no se encontró un array de respuesta en eje plausible "
        "(27 bandas de 1/3 de octava). ¿Es un .cf2/.cf1 exportado por EASE?")


def load_clf(path: str) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]:
    """Lee la respuesta EN EJE de un CLF binario (.cf2/.cf1) ->
    (freq_hz, spl_db, phase_deg=None), misma firma que load_frd.

    Extrae solo la sensibilidad on-axis SPL(f) (dB @ 1W/1m); la directividad se
    descarta (irrelevante bajo Schroeder). El anclaje de nivel se maneja igual
    que un FRD absoluto al construir la SourceResponse.

    Lanza ValueError si el archivo no parece un CLF binario parseable.
    """
    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) < _CLF_ONAXIS_OFFSET + 4 * _CLF_NBANDS:
        raise ValueError(f"CLF '{path}': archivo demasiado corto para ser CF2/CF1.")
    spl = _find_clf_onaxis(data)
    freq = CLF_THIRD_OCTAVE_HZ.copy()
    return freq, spl, None
