from __future__ import annotations

import hashlib
import os
import math
from dataclasses import dataclass
from pathlib import Path
import platform
from queue import Empty, Queue
import shutil
import subprocess
import tempfile
from threading import Event, Lock, Thread, get_ident
from typing import Callable

from .core import (
    AudioItem,
    DEFAULT_PREVIEW_SPEED,
    SAMPLE_RATE,
    TICK_SECONDS,
    _events_to_absolute_spans,
    opl_filter_cutoff_hz,
    parse_pc_speaker_preview_tracks,
    soundcard_music_opl_full_writes,
    synthesize_soundcard_music_wav,
    synthesize_wav,
)


_CURRENT_AUDIO_PROCESS: subprocess.Popen | None = None
_CURRENT_AUDIO_STREAM = None
_CURRENT_PREVIEW_TASK = None
_AUDIO_STREAM_LOCK = Lock()
_PREVIEW_CACHE_VERSION = "audio-preview-v6-ui-async-pc-speaker-wav"


class PreviewRenderTask:
    """Background WAV render shared by atlas previews and simulation effects."""

    def __init__(self, render: Callable[[Callable[[], None]], Path]) -> None:
        self._results: Queue[tuple[Path | None, Exception | None]] = Queue(maxsize=1)
        self._cancelled = Event()

        def run() -> None:
            try:
                self._results.put((render(self.check_cancelled), None))
            except Exception as exc:
                self._results.put((None, exc))

        Thread(target=run, name="audio-preview-render", daemon=True).start()

    def poll(self) -> tuple[Path | None, Exception | None] | None:
        try:
            return self._results.get_nowait()
        except Empty:
            return None

    def cancel(self) -> None:
        self._cancelled.set()

    def check_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise PreviewCancelled("Audio preview render cancelled")


class PreviewCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class AudioPreviewResult:
    """Result of an asynchronous interactive preview start.

    ``mode`` is ``"realtime"`` when a callback stream has already been started,
    or ``"wav"`` when ``path`` points at a cached/generated WAV file that the UI
    still needs to hand to the platform player.
    """

    mode: str
    path: Path | None = None


class AudioPreviewStartTask:
    """Start realtime preview or prepare a WAV completely off the Tk thread."""

    def __init__(self, prepare: Callable[[Callable[[], None]], AudioPreviewResult]) -> None:
        self._results: Queue[tuple[AudioPreviewResult | None, Exception | None]] = Queue(maxsize=1)
        self._cancelled = Event()

        def run() -> None:
            try:
                self._results.put((prepare(self.check_cancelled), None))
            except Exception as exc:
                self._results.put((None, exc))

        Thread(target=run, name="audio-preview-start", daemon=True).start()

    def poll(self) -> tuple[AudioPreviewResult | None, Exception | None] | None:
        try:
            return self._results.get_nowait()
        except Empty:
            return None

    def cancel(self) -> None:
        self._cancelled.set()

    def check_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise PreviewCancelled("Audio preview start cancelled")


class OplRealtimeSource:
    """Incremental Nuked-OPL3 renderer for realtime callback playback."""

    def __init__(self, data: bytes, exe_path: Path | str, *, speed: float) -> None:
        from nuked_opl3 import OPL3, OPL_NATIVE_RATE  # type: ignore

        self._chip = OPL3(sample_rate=OPL_NATIVE_RATE)
        self.sample_rate = int(self._chip.sample_rate)
        self._writes = soundcard_music_opl_full_writes(data, exe_path, speed=speed)
        self._speed = max(0.10, min(8.0, float(speed)))
        self._write_index = 0
        self._sample = 0
        self._tail_samples = self.sample_rate
        self._filter_profile = os.environ.get("AE_OPL_FILTER_PROFILE", "off")
        self._filter_previous = 0.0

    def _write_sample(self, index: int) -> int:
        write = self._writes[index]
        return int(round((write.time_ticks * TICK_SECONDS / self._speed) * self.sample_rate))

    def read(self, frames: int):
        import numpy as np  # type: ignore

        remaining = max(0, int(frames))
        chunks = []
        while remaining:
            while self._write_index < len(self._writes) and self._write_sample(self._write_index) <= self._sample:
                write = self._writes[self._write_index]
                self._chip.write(write.register, write.value)
                self._write_index += 1
            if self._write_index < len(self._writes):
                count = min(remaining, max(1, self._write_sample(self._write_index) - self._sample))
            elif self._tail_samples:
                count = min(remaining, self._tail_samples)
                self._tail_samples -= count
            else:
                break
            chunks.append(np.frombuffer(self._chip.generate_mono(count), dtype="<i2").astype(np.int32))
            self._sample += count
            remaining -= count
        pcm = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int32)
        cutoff_hz = opl_filter_cutoff_hz(self._filter_profile)
        if cutoff_hz and len(pcm):
            alpha = 1.0 - math.exp(-2.0 * math.pi * cutoff_hz / self.sample_rate)
            out = pcm.astype("float64", copy=True)
            previous = self._filter_previous
            for index in range(len(out)):
                previous += alpha * (float(out[index]) - previous)
                out[index] = previous
            self._filter_previous = previous
            pcm = out
        return pcm.clip(-32768, 32767).astype("float32") / 32768.0

    @property
    def finished(self) -> bool:
        return self._write_index >= len(self._writes) and self._tail_samples <= 0


class PcSpeakerRealtimeSource:
    """Incremental square/noise renderer for PC-speaker music and CAF1 SFX."""

    sample_rate = SAMPLE_RATE

    def __init__(self, item: AudioItem, *, speed: float) -> None:
        import numpy as np  # type: ignore

        music = item.kind != "pc-speaker-sfx"
        parsed = parse_pc_speaker_preview_tracks(item.data, music=music, audio_kind=item.kind)
        speed = max(0.10, min(8.0, float(speed)))
        self._tracks = [
            {
                "spans": _events_to_absolute_spans([(freq, dur / speed) for freq, dur in events], self.sample_rate),
                "index": 0,
                "phase": 0.0,
                "seed": 1 + track_no * 12345,
            }
            for track_no, events in enumerate(parsed)
        ]
        self._sample = 0
        self._end = max((spans[-1][2] for track in self._tracks if (spans := track["spans"])), default=0)
        self._np = np

    def read(self, frames: int):
        np = self._np
        frames = max(0, min(int(frames), self._end - self._sample))
        mix = np.zeros(frames, dtype=np.float32)
        if not frames:
            return mix
        block_end = self._sample + frames
        amp = 0.22 / max(1, len(self._tracks))
        for track_no, track in enumerate(self._tracks):
            spans = track["spans"]
            while track["index"] < len(spans) and spans[track["index"]][2] <= self._sample:
                track["index"] += 1
            index = track["index"]
            while index < len(spans):
                freq, start, end = spans[index]
                if start >= block_end:
                    break
                lo = max(start, self._sample) - self._sample
                hi = min(end, block_end) - self._sample
                count = hi - lo
                if count > 0 and freq is not None:
                    if freq < 0:
                        seed = int(track["seed"] + (-freq) * 1103515245 + track_no * 12345)
                        noise = np.empty(count, dtype=np.float32)
                        for offset in range(count):
                            seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
                            noise[offset] = amp if (seed & 0x4000) else -amp
                        track["seed"] = seed
                        mix[lo:hi] += noise
                    else:
                        phase = float(track["phase"])
                        step = 2.0 * math.pi * freq / self.sample_rate
                        phases = phase + step * np.arange(count)
                        mix[lo:hi] += np.where(np.sin(phases) >= 0, amp, -amp)
                        track["phase"] = phase + step * count
                if end > block_end:
                    break
                index += 1
            track["index"] = index
        self._sample = block_end
        return mix.clip(-1.0, 1.0)

    @property
    def finished(self) -> bool:
        return self._sample >= self._end


def play_audio_item_realtime(
    item: AudioItem,
    *,
    speed: float = DEFAULT_PREVIEW_SPEED,
    exe_path: Path | str | None = None,
    stop_current: bool = True,
) -> bool:
    """Start low-latency realtime callback playback for a playable item.

    This is THE interactive playback path (Audio Atlas double-click / Play): it
    starts immediately and never renders a whole-song WAV.  pc-speaker items use
    the square/noise source and sound-card music uses the Nuked-OPL3 chip source;
    both consume the same canonical parser/register-trace code as WAV export, so
    there is no second independent decoder.

    numpy/sounddevice are hard dependencies (requirements.txt) and sound-card
    music needs the nuked_opl3 cffi backend built; a missing one raises loudly
    rather than silently degrading to a different sound.
    Returns False only for items that are not playable (e.g. raw resources).
    """
    if os.environ.get("AE_DISABLE_REALTIME_AUDIO") == "1":
        return False
    import numpy as np  # type: ignore
    import sounddevice as sd  # type: ignore

    if item.kind == "soundcard-music" and exe_path is not None:
        source = OplRealtimeSource(item.data, exe_path, speed=speed)
    elif item.kind in {"pc-speaker-music", "pc-speaker-sfx"}:
        source = PcSpeakerRealtimeSource(item, speed=speed)
    else:
        return False

    if stop_current:
        stop_audio_playback()

    def callback(outdata, frames, _time, _status) -> None:
        pcm = source.read(frames)
        count = len(pcm)
        if count:
            outdata[:count, 0] = pcm
        if count < frames:
            outdata[count:, 0] = np.float32(0.0)
            raise sd.CallbackStop

    stream = sd.OutputStream(
        samplerate=source.sample_rate,
        channels=1,
        dtype="float32",
        blocksize=1024,
        callback=callback,
    )
    with _AUDIO_STREAM_LOCK:
        global _CURRENT_AUDIO_STREAM
        _CURRENT_AUDIO_STREAM = stream
    stream.start()
    return True


def start_audio_preview_async(
    item: AudioItem,
    *,
    speed: float = DEFAULT_PREVIEW_SPEED,
    exe_path: Path | str | None = None,
) -> AudioPreviewStartTask:
    """Start realtime preview off the Tk thread.

    Every playable kind (pc-speaker SFX/music and sound-card music) goes through
    the realtime callback backend - one path, no WAV-cache fallback.  The worker
    thread does the expensive setup (OPL register trace, device open) so Tk
    callbacks stay responsive.  WAV generation is a separate concern used only by
    Export WAV and the Simulation tab.
    """
    global _CURRENT_PREVIEW_TASK

    def prepare(cancel_check: Callable[[], None]) -> AudioPreviewResult:
        cancel_check()
        if not play_audio_item_realtime(item, speed=speed, exe_path=exe_path, stop_current=False):
            raise RuntimeError(f"{item.kind} resources are not playable")
        cancel_check()
        return AudioPreviewResult("realtime")

    # Stop/cancel the previous preview before publishing this task.  The worker
    # may start a realtime stream; it must not call stop_audio_playback() itself
    # afterward because that would cancel the task that is reporting success.
    stop_audio_playback()
    task = AudioPreviewStartTask(prepare)
    _CURRENT_PREVIEW_TASK = task
    return task


def render_preview_async(
    item: AudioItem,
    *,
    speed: float = DEFAULT_PREVIEW_SPEED,
    exe_path: Path | str | None = None,
) -> PreviewRenderTask:
    global _CURRENT_PREVIEW_TASK
    task = PreviewRenderTask(
        lambda cancel_check: temp_preview_wav(item, speed=speed, exe_path=exe_path, cancel_check=cancel_check)
    )
    previous = _CURRENT_PREVIEW_TASK
    _CURRENT_PREVIEW_TASK = task
    if previous is not None:
        previous.cancel()
    return task


def _preview_cache_path(item: AudioItem, *, speed: float, exe_path: Path | str | None) -> Path:
    """Return a content-addressed preview path so repeated playback is instant."""
    digest = hashlib.blake2b(digest_size=12)
    digest.update(_PREVIEW_CACHE_VERSION.encode("ascii"))
    digest.update(item.kind.encode("utf-8"))
    digest.update(item.data)
    digest.update(f"{float(speed):.6g}".encode("ascii"))
    digest.update(os.environ.get("AE_OPL_FILTER_PROFILE", "off").encode("ascii", errors="ignore"))
    if exe_path is not None:
        exe = Path(exe_path)
        try:
            stat = exe.stat()
            digest.update(str(exe.resolve()).encode("utf-8"))
            digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode("ascii"))
        except OSError:
            digest.update(str(exe).encode("utf-8"))
    temp_dir = Path(tempfile.gettempdir()) / "ae_audio_atlas"
    temp_dir.mkdir(parents=True, exist_ok=True)
    safe = f"{item.kind}_{item.archive_name}_{item.resource_index}_{item.sound_id if item.sound_id is not None else 'res'}"
    return temp_dir / f"{safe}_{digest.hexdigest()}.wav"


def _cached_preview(path: Path, render, *, cancel_check: Callable[[], None] | None = None) -> Path:
    """Render a preview once and reuse complete cached WAV files."""
    if path.is_file() and path.stat().st_size > 44:
        return path
    if cancel_check is not None:
        cancel_check()
    pending = path.with_name(f"{path.stem}.{get_ident()}.tmp.wav")
    try:
        render(pending)
        if cancel_check is not None:
            cancel_check()
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)
    return path

def stop_audio_playback() -> None:
    """Stop the current Audio Atlas WAV preview, if the platform player allows it."""
    global _CURRENT_AUDIO_PROCESS, _CURRENT_AUDIO_STREAM, _CURRENT_PREVIEW_TASK
    if _CURRENT_PREVIEW_TASK is not None:
        _CURRENT_PREVIEW_TASK.cancel()
        _CURRENT_PREVIEW_TASK = None
    with _AUDIO_STREAM_LOCK:
        stream = _CURRENT_AUDIO_STREAM
        _CURRENT_AUDIO_STREAM = None
    if stream is not None:
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass
    system = platform.system().lower()
    if system == "windows":
        try:
            import winsound
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass
    if _CURRENT_AUDIO_PROCESS is not None:
        proc = _CURRENT_AUDIO_PROCESS
        _CURRENT_AUDIO_PROCESS = None
        if proc.poll() is None:
            proc.terminate()


def play_audio_file(path: Path | str) -> None:
    global _CURRENT_AUDIO_PROCESS
    path = Path(path)
    stop_audio_playback()
    system = platform.system().lower()
    if system == "windows":
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        return
    for cmd in (["afplay", str(path)], ["aplay", str(path)], ["paplay", str(path)], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)]):
        if shutil.which(cmd[0]):
            _CURRENT_AUDIO_PROCESS = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    raise RuntimeError("No audio player found (tried afplay/aplay/paplay/ffplay). Export WAV instead.")


def temp_preview_wav(item: AudioItem, *, speed: float = DEFAULT_PREVIEW_SPEED, exe_path: Path | str | None = None, cancel_check: Callable[[], None] | None = None) -> Path:
    path = _preview_cache_path(item, speed=speed, exe_path=exe_path)
    # Sound-card music is OPL FM, not a square-wave PC-speaker tone. AEPROG.EXE
    # provides the FM patch table needed by the single Nuked-OPL3 render path.
    if item.kind == "soundcard-music" and exe_path is not None:
        return _cached_preview(
            path,
            lambda pending: synthesize_soundcard_music_wav(
                item.data, exe_path, pending, speed=speed, cancel_check=cancel_check
            ),
            cancel_check=cancel_check,
        )
    return _cached_preview(
        path,
        lambda pending: synthesize_wav(
            item.data,
            pending,
            music=item.kind != "pc-speaker-sfx",
            speed=speed,
            audio_kind=item.kind,
            cancel_check=cancel_check,
        ),
        cancel_check=cancel_check,
    )
