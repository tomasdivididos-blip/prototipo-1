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
