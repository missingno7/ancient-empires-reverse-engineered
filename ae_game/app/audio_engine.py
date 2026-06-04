"""Realtime game audio: looping music mixed with transient SFX.

The original game pairs each music track as PC-speaker (resource ``N``) and
sound-card/OPL (resource ``N+1``); ``AEPROG`` 0xd5f9 plays one half based on the
selected sound device.  Here the sound-card (OPL) mix is the default, with a
runtime switch to the PC-speaker version.

The output stream runs at the PC-speaker ``SAMPLE_RATE`` so PC-speaker SFX mix
directly; sound-card music is rendered through the OPL emulator and resampled to
that rate once per track (in a background thread, cached).  Everything degrades
to a silent no-op if numpy/sounddevice or the audio device are unavailable.
"""
from __future__ import annotations

from threading import Lock, Thread

from ancient_empires.audio.core import SAMPLE_RATE, build_audio_atlas

MUSIC_ARCHIVE = "AE001.DAT"
MUSIC_BASE_INDEX = 115  # AE001 resource 0x73, PC-speaker half of the first pair


def level_music_base_index(level_index: int) -> int:
    """PC-speaker music resource for a level (AEPROG 0x4874, stage G = 2*level).

    ``index = 115 + (G//8)*4 + (G & 2)``; the final region (G//8 == 4) instead
    samples one track per earlier region (``115 + ((G&7)//2)*4``).  The
    sound-card half is the returned index + 1.
    """
    g = 2 * max(0, int(level_index))
    if g // 8 == 4:
        return MUSIC_BASE_INDEX + ((g & 7) // 2) * 4
    return MUSIC_BASE_INDEX + (g // 8) * 4 + (g & 2)


class GameAudioEngine:
    """Mixes one looping music track with overlapping one-shot SFX."""

    def __init__(self, project, *, music_mode: str = "soundcard") -> None:
        self.available = False
        self._sound_enabled = True
        self._music_enabled = True
        self._music_mode = music_mode  # "soundcard" or "pcspeaker"
        self._lock = Lock()
        self._music = None          # numpy float32 mono, or None
        self._music_pos = 0
        self._music_token = 0       # guards against stale background renders
        self._active_sfx: list[list] = []
        self._sfx_cache: dict[int, object] = {}
        self._music_cache: dict[str, object] = {}
        self._stream = None

        try:
            import numpy as np  # type: ignore
            import sounddevice as sd  # type: ignore
        except Exception:
            return
        self._np = np
        self._sd = sd
        self._exe_path = getattr(project, "exe", None)

        try:
            atlas = build_audio_atlas(project)
        except Exception:
            return
        self._sfx_items = {
            item.sound_id: item
            for item in atlas
            if item.kind == "pc-speaker-sfx" and item.sound_id is not None
        }
        # Music resources keyed by (archive, resource_index) for both halves.
        self._music_by_index = {
            (item.archive_name, item.resource_index): item
            for item in atlas
            if item.kind in ("pc-speaker-music", "soundcard-music")
        }

        try:
            self._stream = sd.OutputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=1024,
                callback=self._callback,
            )
            self._stream.start()
            self.available = True
        except Exception:
            self._stream = None

    # ── audio thread ────────────────────────────────────────────────────────
    def _callback(self, outdata, frames, time_info, status) -> None:  # noqa: ARG002
        np = self._np
        mix = np.zeros(frames, dtype=np.float32)
        with self._lock:
            music = self._music
            if self._music_enabled and music is not None and len(music):
                pos = self._music_pos
                filled = 0
                while filled < frames:
                    chunk = music[pos:pos + (frames - filled)]
                    if not len(chunk):
                        pos = 0
                        continue
                    mix[filled:filled + len(chunk)] += chunk
                    filled += len(chunk)
                    pos += len(chunk)
                    if pos >= len(music):
                        pos = 0
                self._music_pos = pos
            if self._sound_enabled and self._active_sfx:
                still_playing = []
                for entry in self._active_sfx:
                    samples, pos = entry
                    chunk = samples[pos:pos + frames]
                    mix[:len(chunk)] += chunk
                    pos += len(chunk)
                    if pos < len(samples):
                        entry[1] = pos
                        still_playing.append(entry)
                self._active_sfx = still_playing
        np.clip(mix, -1.0, 1.0, out=mix)
        outdata[:, 0] = mix

    # ── rendering helpers ───────────────────────────────────────────────────
    def _render_pcspeaker(self, item):
        from ancient_empires.audio.playback import PcSpeakerRealtimeSource

        source = PcSpeakerRealtimeSource(item, speed=1.0)
        chunks = []
        while not source.finished:
            chunk = source.read(8192)
            if not len(chunk):
                break
            chunks.append(chunk)
        return self._np.concatenate(chunks) if chunks else None

    def _render_soundcard(self, item):
        from ancient_empires.audio.playback import OplRealtimeSource

        source = OplRealtimeSource(item.data, self._exe_path, speed=1.0)
        chunks = []
        while not source.finished:
            chunk = source.read(8192)
            if not len(chunk):
                break
            chunks.append(chunk)
        if not chunks:
            return None
        opl = self._np.concatenate(chunks)
        return self._resample(opl, source.sample_rate, SAMPLE_RATE)

    def _resample(self, samples, src_rate, dst_rate):
        np = self._np
        if src_rate == dst_rate or not len(samples):
            return samples
        n_out = int(len(samples) * dst_rate / src_rate)
        if n_out <= 0:
            return None
        x_new = np.linspace(0.0, len(samples) - 1, n_out)
        return np.interp(x_new, np.arange(len(samples)), samples).astype(np.float32)

    def _render_music_item(self, item):
        try:
            if item.kind == "soundcard-music":
                return self._render_soundcard(item)
            return self._render_pcspeaker(item)
        except Exception:
            return None

    # ── public API ──────────────────────────────────────────────────────────
    def play_sfx(self, sound_id: int) -> None:
        if not self.available or not self._sound_enabled:
            return
        samples = self._sfx_cache.get(sound_id)
        if samples is None and sound_id not in self._sfx_cache:
            item = self._sfx_items.get(int(sound_id))
            samples = None if item is None else self._safe_render_pcspeaker(item)
            self._sfx_cache[sound_id] = samples
        if samples is None or not len(samples):
            return
        with self._lock:
            self._active_sfx.append([samples, 0])

    def _safe_render_pcspeaker(self, item):
        try:
            return self._render_pcspeaker(item)
        except Exception:
            return None

    def play_level_music(self, level_index: int) -> None:
        """Loop the music track that the original maps to this level."""
        if not self.available:
            return
        base = level_music_base_index(level_index)
        index = base + 1 if self._music_mode == "soundcard" else base
        item = self._music_by_index.get((MUSIC_ARCHIVE, index))
        if item is None:  # fall back to the PC-speaker half if a pair is missing
            item = self._music_by_index.get((MUSIC_ARCHIVE, base))
        self._set_music(item)

    def _set_music(self, item) -> None:
        if item is None:
            return
        with self._lock:
            self._music_token += 1
            token = self._music_token
        cached = self._music_cache.get(item.key)
        if cached is not None:
            self._apply_music(cached, token)
            return

        def render() -> None:
            samples = self._render_music_item(item)
            if samples is not None:
                self._music_cache[item.key] = samples
            self._apply_music(samples, token)

        Thread(target=render, name="ae-music-render", daemon=True).start()

    def _apply_music(self, samples, token) -> None:
        with self._lock:
            if token != self._music_token:
                return  # a newer request superseded this one
            self._music = samples
            self._music_pos = 0

    def set_music_mode(self, mode: str, level_index: int | None = None) -> None:
        self._music_mode = "pcspeaker" if mode == "pcspeaker" else "soundcard"
        if level_index is not None:
            self.play_level_music(level_index)

    def music_mode(self) -> str:
        return self._music_mode

    def set_sound_enabled(self, enabled: bool) -> None:
        self._sound_enabled = bool(enabled)
        if not enabled:
            with self._lock:
                self._active_sfx = []

    def set_music_enabled(self, enabled: bool) -> None:
        self._music_enabled = bool(enabled)

    def shutdown(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        self.available = False
