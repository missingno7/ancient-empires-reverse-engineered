from __future__ import annotations

import argparse
import wave
from pathlib import Path

import numpy as np


def read_wav(path: Path) -> tuple[int, np.ndarray]:
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())
    if width != 2:
        raise SystemExit(f"only 16-bit PCM WAV is supported: {path}")
    data = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return sr, data - float(np.mean(data))


def spectral_stats(samples: np.ndarray, sr: int) -> tuple[float, float]:
    win = 4096
    hop = 2048
    freqs = np.fft.rfftfreq(win, 1.0 / sr)
    centroids: list[float] = []
    rolloffs: list[float] = []
    window = np.hanning(win)
    for start in range(0, max(0, len(samples) - win), hop):
        mag = np.abs(np.fft.rfft(samples[start:start + win] * window))
        total = float(mag.sum())
        if total <= 1e-8:
            continue
        centroids.append(float((freqs * mag).sum() / total))
        cumulative = np.cumsum(mag)
        idx = int(np.searchsorted(cumulative, 0.85 * cumulative[-1]))
        rolloffs.append(float(freqs[min(idx, len(freqs) - 1)]))
    return float(np.median(centroids)), float(np.median(rolloffs))


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare simple spectrum stats for two WAV files")
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    ref_sr, ref = read_wav(args.reference)
    cand_sr, cand = read_wav(args.candidate)
    if ref_sr != cand_sr:
        raise SystemExit(f"sample rates differ: {ref_sr} vs {cand_sr}")
    ref_centroid, ref_rolloff = spectral_stats(ref, ref_sr)
    cand_centroid, cand_rolloff = spectral_stats(cand, cand_sr)
    print(f"reference centroid: {ref_centroid:.1f} Hz")
    print(f"candidate centroid: {cand_centroid:.1f} Hz")
    print(f"reference 85% rolloff: {ref_rolloff:.1f} Hz")
    print(f"candidate 85% rolloff: {cand_rolloff:.1f} Hz")


if __name__ == "__main__":
    main()
