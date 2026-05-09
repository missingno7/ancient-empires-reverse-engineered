from __future__ import annotations

from pathlib import Path
import os
import platform
import shutil
import subprocess
import tempfile

from .core import AudioItem, DEFAULT_PREVIEW_SPEED, synthesize_wav

_CURRENT_AUDIO_PROCESS: subprocess.Popen | None = None

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


def temp_preview_wav(item: AudioItem, *, speed: float = DEFAULT_PREVIEW_SPEED) -> Path:
    temp_dir = Path(tempfile.gettempdir()) / "ae_audio_atlas"
    temp_dir.mkdir(parents=True, exist_ok=True)
    safe = f"{item.kind}_{item.archive_name}_{item.resource_index}_{item.sound_id if item.sound_id is not None else 'res'}"
    path = temp_dir / f"{safe}.wav"
    return synthesize_wav(item.data, path, music=item.kind != "pc-speaker-sfx", speed=speed, audio_kind=item.kind)
