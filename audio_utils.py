"""audio_utils.py
================
Utilidades de audio para escuchar la FRF de la sala.

Backend de reproduccion segun plataforma (sin DLLs externas):
    Windows -> winsound (built-in)
    macOS   -> afplay   (built-in)
    Linux   -> aplay / paplay / ffplay (el primero disponible)
         Requiere: numpy, scipy.

Flujo:
    noise    = pink_noise(duration=4.0)
    filtered = apply_frf_filter(noise, H, f_axis)
    play(filtered)
    stop()
"""

from __future__ import annotations

import os
import sys
import shutil
import tempfile
import subprocess
import numpy as np
from scipy.io.wavfile import write as _wav_write
from scipy.signal import fftconvolve

# Backend de reproduccion: winsound solo existe en Windows. En Mac/Linux
# reproducimos lanzando el reproductor del sistema como subproceso.
try:
    import winsound                    # built-in solo en Windows
except Exception:                      # noqa: BLE001  (Mac/Linux)
    winsound = None

SR = 44100   # sample rate por defecto

# Ruta del archivo WAV temporal (se sobreescribe en cada play)
_tmpfile: str | None = None
# Proceso de reproduccion en Mac/Linux (afplay/aplay/...); None en Windows.
_proc = None

# ---------------------------------------------------------------------------
# Generacion de ruido rosa
# ---------------------------------------------------------------------------
def pink_noise(duration: float = 4.0, sr: int = SR) -> np.ndarray:
    """Ruido rosa (densidad espectral ∝ 1/f), normalizado a ±1.

    Algoritmo: ruido blanco → filtro 1/√f en dominio de frecuencia.
    """
    n = int(sr * duration)
    rng   = np.random.default_rng()
    white = rng.standard_normal(n)
    freqs = np.fft.rfftfreq(n)
    freqs[0] = 1e-9                       # evitar div/0 en DC
    filt  = 1.0 / np.sqrt(freqs)
    filt[0] = 0.0                         # sin DC
    pink = np.fft.irfft(np.fft.rfft(white) * filt, n=n)
    peak = np.max(np.abs(pink))
    return pink / peak if peak > 0 else pink


# ---------------------------------------------------------------------------
# FRF → respuesta al impulso
# ---------------------------------------------------------------------------
def frf_to_ir(H: np.ndarray, f_axis: np.ndarray,
              sr: int = SR, ir_duration: float = 0.6) -> np.ndarray:
    """Convierte la FRF H(f) en una respuesta al impulso via IFFT.

    Frecuencias fuera del rango [f_axis[0], f_axis[-1]] → 0 (pasa-banda).
    Se aplica un fade de Hann en los bordes para evitar discontinuidades.
    """
    n     = int(sr * ir_duration)
    freqs = np.fft.rfftfreq(n, d=1.0 / sr)

    # Interpolar magnitud y fase (fase desenvolta para continuidad)
    H_abs   = np.abs(H)
    H_phase = np.unwrap(np.angle(H))
    abs_i   = np.interp(freqs, f_axis, H_abs,   left=0.0, right=0.0)
    pha_i   = np.interp(freqs, f_axis, H_phase, left=0.0, right=0.0)

    # Fade Hann en los bordes del rango definido (~5 % de ancho)
    n_edge  = max(2, len(freqs) // 20)
    fade    = np.hanning(2 * n_edge)
    i_lo    = np.searchsorted(freqs, f_axis[0])
    i_hi    = np.searchsorted(freqs, f_axis[-1])
    sl_lo   = slice(max(0, i_lo - n_edge), i_lo)
    sl_hi   = slice(i_hi, min(len(freqs), i_hi + n_edge))
    n_lo    = sl_lo.stop - sl_lo.start
    n_hi    = sl_hi.stop - sl_hi.start
    if n_lo > 0:
        abs_i[sl_lo] *= fade[n_edge - n_lo:n_edge]
    if n_hi > 0:
        abs_i[sl_hi] *= fade[n_edge:n_edge + n_hi]

    H_full = abs_i * np.exp(1j * pha_i)
    return np.fft.irfft(H_full, n=n)


# ---------------------------------------------------------------------------
# Aplicar FRF como filtro al ruido rosa
# ---------------------------------------------------------------------------
# Ganancia equivalente +6 dB (2x amplitud) implementada con soft-clipping
# tanh para que los picos transitorios no saturen feo. Drive = 2.5 sube el
# RMS aprox 2x y conserva headroom; tanh tiene curva suave (≈ lineal cerca
# de cero, satura graciosamente cerca de ±1). Comparado con el viejo
# normalizado a 0.85, el resultado es claramente mas audible sin distorsion
# perceptible en material como ruido rosa filtrado.
_DRIVE = 2.5


def _soft_clip(x: np.ndarray, drive: float = _DRIVE) -> np.ndarray:
    """Saturador suave: x → tanh(drive·x)/tanh(drive). Mantiene amplitudes
    chicas casi sin cambio y comprime picos elasticamente."""
    return np.tanh(drive * x) / np.tanh(drive)


def _fade_inout(sig: np.ndarray, sr: int,
                fade_in_ms: float = 10.0,
                fade_out_ms: float = 50.0) -> np.ndarray:
    """Aplica fade-in y fade-out lineales para evitar el "pop" al arrancar
    y, sobre todo, al finalizar la reproduccion (la discontinuidad de
    truncamiento es lo que genera el chasquido seco al final)."""
    n = len(sig)
    n_in = max(1, int(sr * fade_in_ms / 1000.0))
    n_out = max(1, int(sr * fade_out_ms / 1000.0))
    if n_in + n_out >= n:
        return sig
    out = sig.copy()
    # Fade-in lineal
    out[:n_in] *= np.linspace(0.0, 1.0, n_in, endpoint=True)
    # Fade-out lineal (mas largo: 50 ms cubre la ventana de buffer del DAC
    # y la cola de la convolucion)
    out[-n_out:] *= np.linspace(1.0, 0.0, n_out, endpoint=True)
    return out


def apply_frf_filter(signal: np.ndarray, H: np.ndarray,
                     f_axis: np.ndarray, sr: int = SR) -> np.ndarray:
    """Filtra `signal` con H(f) por convolución en frecuencia.

    Pipeline:
      1. IFFT(H) → respuesta al impulso (FRF en tiempo).
      2. Convolucion en frecuencia con el ruido rosa.
      3. Normalizar el peak a ±1 para tener todo el headroom disponible.
      4. Boost de ganancia +6 dB equivalente via soft-clipping tanh.
      5. Fade-in 10 ms + fade-out 50 ms (mata el pop al final).
    """
    ir       = frf_to_ir(H, f_axis, sr=sr,
                         ir_duration=min(len(signal) / sr, 0.8))
    filtered = fftconvolve(signal, ir, mode='full')[:len(signal)]

    # 1. Normalizar el peak a 1.0 (todo el headroom disponible).
    peak = np.max(np.abs(filtered))
    if peak > 1e-9:
        filtered = filtered / peak

    # 2. Subir ganancia con soft-clipping. Resultado: ~2x amplitud RMS,
    #    pero peak limitado a ±1 (sin clipeo duro).
    filtered = _soft_clip(filtered, drive=_DRIVE)

    # 3. Escalar el peak final a 0.98 (deja 0.16 dB de headroom para evitar
    #    saturacion en el conversor DAC del sistema).
    peak = np.max(np.abs(filtered))
    if peak > 1e-9:
        filtered = filtered / peak * 0.98

    # 4. Fade-in/out para eliminar el "pop" al arrancar y al finalizar.
    filtered = _fade_inout(filtered, sr,
                            fade_in_ms=10.0, fade_out_ms=50.0)
    return filtered.astype(np.float32)


# ---------------------------------------------------------------------------
# Reproduccion (Windows: winsound | macOS: afplay | Linux: aplay/paplay/ffplay)
# ---------------------------------------------------------------------------
def _player_cmd(path: str):
    """Comando de reproduccion para Mac/Linux, o None si no hay reproductor.

    macOS trae `afplay` de fabrica. En Linux probamos aplay/paplay/ffplay.
    """
    if sys.platform == "darwin":
        return ["afplay", path]
    for name, extra in (("aplay", []),
                        ("paplay", []),
                        ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"])):
        exe = shutil.which(name)
        if exe:
            return [exe] + extra + [path]
    return None


def play(signal: np.ndarray, sr: int = SR) -> None:
    """Escribe un WAV temporal y lo reproduce de forma asincrona.

    Windows usa winsound (winmm.dll, built-in). macOS usa afplay (built-in).
    Linux usa aplay/paplay/ffplay (el primero disponible). Ninguno requiere
    DLLs ni paquetes de terceros.

    Anti-pop al final: ademas del fade-out en `apply_frf_filter`, agregamos
    100 ms de silencio al final del WAV. Esto evita que el chasquido del
    buffer de hardware coincida con muestras no-cero (el reproductor corta
    seco al EOF; con cola de ceros el ultimo sample reproducido siempre es 0).
    """
    global _tmpfile
    stop()   # detener reproduccion anterior

    # Convertir a int16 estereo (16 bit, 44.1 kHz, 2 canales)
    sig_int = np.clip(signal * 32767.0, -32768, 32767).astype(np.int16)
    # Cola de silencio (100 ms) — todos ceros, anti-pop al EOF
    n_silence = int(sr * 0.10)
    silence = np.zeros(n_silence, dtype=np.int16)
    sig_int = np.concatenate([sig_int, silence])
    sig_stereo = np.column_stack([sig_int, sig_int])   # (N, 2) L=R

    # Escribir WAV temporal: 16 bit, 44100 Hz, estereo
    _tmpfile = tempfile.mktemp(suffix='.wav')
    _wav_write(_tmpfile, sr, sig_stereo)

    # Reproducir asincronamente (no bloquea el hilo de Qt).
    global _proc
    if winsound is not None:                      # Windows
        winsound.PlaySound(
            _tmpfile,
            winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
        )
    else:                                          # macOS / Linux
        cmd = _player_cmd(_tmpfile)
        if cmd is not None:
            # Popen no bloquea; guardamos el handle para cortar en stop().
            _proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )


def stop() -> None:
    """Detiene la reproduccion y elimina el archivo temporal."""
    global _tmpfile, _proc
    if winsound is not None:
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass
    if _proc is not None:
        try:
            _proc.terminate()
        except Exception:
            pass
        _proc = None
    if _tmpfile and os.path.exists(_tmpfile):
        try:
            os.unlink(_tmpfile)
        except Exception:
            pass
        _tmpfile = None


def check_audio() -> str | None:
    """Devuelve None si hay backend de audio disponible, o un mensaje de error."""
    try:
        from scipy.io.wavfile import write   # noqa
    except ImportError:
        return "scipy no instalado.  pip install scipy"
    if winsound is not None:                    # Windows
        return None
    if _player_cmd("dummy.wav") is not None:    # macOS (afplay) / Linux
        return None
    return ("No se encontro reproductor de audio del sistema. "
            "En Linux instala alsa-utils (aplay) o pulseaudio (paplay).")
