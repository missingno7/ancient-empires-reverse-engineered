from __future__ import annotations

import argparse
from pathlib import Path
import wave


def read_wav_mono(path: Path) -> tuple[list[float], int]:
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    if sampwidth != 2:
        raise ValueError(f"Only 16-bit PCM WAV is supported: {path}")
    vals: list[int] = []
    for i in range(0, len(raw), 2):
        v = int.from_bytes(raw[i:i + 2], "little", signed=True)
        vals.append(v)
    if channels == 2:
        mono = [(vals[i] + vals[i + 1]) / (2.0 * 32768.0) for i in range(0, len(vals) - 1, 2)]
    elif channels == 1:
        mono = [v / 32768.0 for v in vals]
    else:
        raise ValueError(f"Unsupported channel count {channels}: {path}")
    return mono, rate


def rough_zero_crossing_frequencies(samples: list[float], rate: int, *, window_s: float = 0.020, hop_s: float = 0.010) -> list[float]:
    """Return a rough square-wave pitch contour for PC-speaker captures.

    This is intentionally simple and dependency-free. It is meant for quick
    verification of CAF1 sweeps, not for high-quality pitch detection.
    """
    win = max(8, int(window_s * rate))
    hop = max(1, int(hop_s * rate))
    out: list[float] = []
    for start in range(0, max(0, len(samples) - win), hop):
        seg = samples[start:start + win]
        if max(abs(v) for v in seg) < 0.02:
            continue
        mean = sum(seg) / len(seg)
        signs = [1 if v >= mean else -1 for v in seg]
        crossings: list[int] = []
        for i in range(1, len(signs)):
            if signs[i] != signs[i - 1]:
                crossings.append(i)
        if len(crossings) < 3:
            continue
        diffs = sorted(crossings[i] - crossings[i - 1] for i in range(1, len(crossings)))
        half_period = diffs[len(diffs) // 2] / rate
        if half_period > 0:
            out.append(1.0 / (2.0 * half_period))
    return out


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct / 100.0)))
    return ordered[idx]


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize PC-speaker-ish WAV captures for audio reverse engineering.")
    parser.add_argument("wav", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.wav:
        samples, rate = read_wav_mono(path)
        freqs = rough_zero_crossing_frequencies(samples, rate)
        duration = len(samples) / rate
        if freqs:
            print(f"{path}: duration={duration:.6f}s median={percentile(freqs, 50):.2f}Hz p10={percentile(freqs, 10):.2f}Hz p90={percentile(freqs, 90):.2f}Hz")
        else:
            print(f"{path}: duration={duration:.6f}s no stable pitch estimate")


if __name__ == "__main__":
    main()
