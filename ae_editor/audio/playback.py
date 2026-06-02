from __future__ import annotations

import hashlib
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile

from .core import AudioItem, DEFAULT_PREVIEW_SPEED, synthesize_soundcard_music_wav, synthesize_wav


_CURRENT_AUDIO_PROCESS: subprocess.Popen | None = None
_PREVIEW_CACHE_VERSION = "audio-preview-v2-ym3812"


def _preview_cache_path(item: AudioItem, *, speed: float, exe_path: Path | str | None) -> Path:
    """Return a content-addressed preview path so repeated playback is instant."""
    digest = hashlib.blake2b(digest_size=12)
    digest.update(_PREVIEW_CACHE_VERSION.encode("ascii"))
    digest.update(item.kind.encode("utf-8"))
    digest.update(item.data)
    digest.update(f"{float(speed):.6g}".encode("ascii"))
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


def _cached_preview(path: Path, render) -> Path:
    """Render a preview once and reuse complete cached WAV files."""
    if path.is_file() and path.stat().st_size > 44:
        return path
    pending = path.with_suffix(".tmp.wav")
    try:
        render(pending)
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)
    return path

def stop_audio_playback() -> None:
    """Stop the current Audio Atlas WAV preview, if the platform player allows it."""
    global _CURRENT_AUDIO_PROCESS
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


def temp_preview_wav(item: AudioItem, *, speed: float = DEFAULT_PREVIEW_SPEED, exe_path: Path | str | None = None) -> Path:
    path = _preview_cache_path(item, speed=speed, exe_path=exe_path)
    # Sound-card music is OPL FM, not a square-wave PC-speaker tone.  When we have
    # AEPROG.EXE (for the FM patch table), use the YM3812 chip renderer. It falls
    # back to the lightweight FM preview when the optional binding is missing,
    # then to the generic renderer if the resource has no OPL header.
    if item.kind == "soundcard-music" and exe_path is not None:
        try:
            return _cached_preview(
                path,
                lambda pending: synthesize_soundcard_music_wav(item.data, exe_path, pending, speed=speed),
            )
        except Exception:
            pass
    return _cached_preview(
        path,
        lambda pending: synthesize_wav(
            item.data,
            pending,
            music=item.kind != "pc-speaker-sfx",
            speed=speed,
            audio_kind=item.kind,
        ),
    )
