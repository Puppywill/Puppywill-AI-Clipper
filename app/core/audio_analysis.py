"""
audio_analysis.py
------------------
Extrae el audio de un video largo con FFmpeg y calcula, cuadro a cuadro
(ventanas de ~0.5s), un conjunto de señales numéricas que luego usa el
scorer para encontrar momentos "explosivos": gritos, risas, subidas
bruscas de volumen, silencios seguidos de picos, etc.

No depende de ninguna librería pesada (solo numpy + ffmpeg vía subprocess),
así que corre igual de bien en CPU que en GPU. Es rápido incluso para
streams de 3+ horas porque procesamos en float32 vectorizado con numpy.
"""
from __future__ import annotations

import subprocess
import shutil
import numpy as np
from dataclasses import dataclass
from pathlib import Path


SAMPLE_RATE = 16000          # mono 16kHz es suficiente para el análisis de energía y es rápido de decodificar
WINDOW_SECONDS = 0.5          # resolución temporal del análisis de energía
HOP_SECONDS = 0.5              # sin solape para rapidez; se puede bajar a 0.25 para más precisión


def _ffmpeg_bin() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError(
            "No se encontró FFmpeg en el PATH. Instálalo desde https://ffmpeg.org/download.html "
            "o con 'winget install ffmpeg' en Windows."
        )
    return exe


def extract_audio_wav(video_path: str, out_wav_path: str, sample_rate: int = SAMPLE_RATE) -> str:
    """Extrae el audio completo del video a un WAV mono PCM16 a `sample_rate` Hz,
    para el análisis de energía (picos, risas)."""
    ffmpeg = _ffmpeg_bin()
    out_wav_path = str(out_wav_path)
    Path(out_wav_path).parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        ffmpeg, "-y", "-i", str(video_path),
        "-vn",                      # sin video
        "-ac", "1",                  # mono
        "-ar", str(sample_rate),     # sample rate
        "-acodec", "pcm_s16le",
        out_wav_path,
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg falló extrayendo audio:\n{proc.stderr.decode(errors='ignore')}")
    return out_wav_path


def read_wav_mono16(path: str) -> tuple[np.ndarray, int]:
    """Lee un WAV PCM16 mono sin dependencias externas (usa el módulo wave de stdlib)."""
    import wave
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return audio, sr


@dataclass
class AudioFeatures:
    times: np.ndarray            # tiempo (s) del centro de cada ventana
    rms: np.ndarray              # energía RMS por ventana (0..1 aprox)
    rms_db: np.ndarray           # RMS en dB (más perceptual)
    delta: np.ndarray            # cambio brusco de energía respecto a la ventana anterior
    peak_score: np.ndarray       # 0..1, qué tan "pico/grito" es esa ventana
    laughter_score: np.ndarray   # 0..1, heurística de risa (energía alta + variabilidad rápida)
    duration_sec: float


def _moving_avg(x: np.ndarray, window: int) -> np.ndarray:
    if window <= 1:
        return x
    kernel = np.ones(window) / window
    return np.convolve(x, kernel, mode="same")


def analyze_audio(wav_path: str, window_seconds: float = WINDOW_SECONDS) -> AudioFeatures:
    """Calcula features de energía/emoción por ventanas fijas sobre todo el audio.

    Señales calculadas:
      - rms / rms_db: volumen por ventana.
      - delta: |rms[i] - rms[i-1]| normalizado -> detecta "explosiones" de volumen
        (gritos, disparos, público reaccionando).
      - peak_score: combina rms alto + delta alto, normalizado 0..1 por percentiles
        de todo el stream (así se adapta al nivel de audio de cada streamer).
      - laughter_score: heurística basada en la tasa de cruces por cero de la
        envolvente de energía en ventanas cortas (la risa tiene un patrón de
        pulsos repetidos característico) combinada con rms medio-alto.
    """
    audio, sr = read_wav_mono16(wav_path)
    total_samples = len(audio)
    win = int(window_seconds * sr)
    if win < 1:
        win = 1
    n_windows = max(1, total_samples // win)

    trimmed = audio[: n_windows * win]
    frames = trimmed.reshape(n_windows, win)

    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1) + 1e-12).astype(np.float32)
    rms_db = 20.0 * np.log10(np.maximum(rms, 1e-6))

    # cambio brusco respecto a la ventana anterior (para detectar explosiones)
    delta = np.zeros_like(rms)
    delta[1:] = np.abs(rms[1:] - rms[:-1])

    # normalización robusta por percentiles (para adaptarse a distintos niveles de mezcla)
    def _norm01(x: np.ndarray) -> np.ndarray:
        lo, hi = np.percentile(x, 5), np.percentile(x, 97)
        if hi - lo < 1e-9:
            return np.zeros_like(x)
        return np.clip((x - lo) / (hi - lo), 0.0, 1.0)

    rms_n = _norm01(rms)
    delta_n = _norm01(delta)
    peak_score = np.clip(0.6 * rms_n + 0.4 * delta_n, 0.0, 1.0)

    # Heurística de risa: dentro de cada ventana "grande", medimos cuántas
    # sub-ventanas pequeñas tienen picos de energía repetidos (patrón pulsante)
    sub_win = max(1, win // 8)
    laughter = np.zeros(n_windows, dtype=np.float32)
    for i in range(n_windows):
        seg = frames[i]
        n_sub = max(1, len(seg) // sub_win)
        sub = seg[: n_sub * sub_win].reshape(n_sub, sub_win)
        sub_rms = np.sqrt(np.mean(sub.astype(np.float64) ** 2, axis=1) + 1e-12)
        if sub_rms.mean() < 1e-6:
            continue
        # tasa de "pulsos": cuántas sub-ventanas superan la media local
        pulses = np.sum(sub_rms > (sub_rms.mean() * 1.15))
        pulse_rate = pulses / max(1, n_sub)
        # la risa tiene pulse_rate medio (ni plano ni caótico) + energía medio-alta
        laughter[i] = pulse_rate

    laughter_n = _norm01(laughter)
    laughter_score = np.clip(laughter_n * (0.4 + 0.6 * rms_n), 0.0, 1.0)

    times = (np.arange(n_windows) * window_seconds + window_seconds / 2.0).astype(np.float32)
    duration_sec = total_samples / sr

    return AudioFeatures(
        times=times, rms=rms, rms_db=rms_db, delta=delta,
        peak_score=peak_score, laughter_score=laughter_score,
        duration_sec=duration_sec,
    )
