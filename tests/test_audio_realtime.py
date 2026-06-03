from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from ancient_empires.audio.playback import PcSpeakerRealtimeSource, play_audio_item_realtime
from tests.test_audio_playback_cache import _item


class _Source:
    sample_rate = 49715

    def read(self, frames):
        return np.full(frames, 0.25, dtype=np.float32)


class _Stream:
    instances = []

    def __init__(self, **kwargs):
        self.callback = kwargs["callback"]
        self.started = False
        self.stopped = False
        self.closed = False
        _Stream.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class _CallbackStop(Exception):
    pass


def _fake_sounddevice():
    _Stream.instances.clear()
    return SimpleNamespace(OutputStream=_Stream, CallbackStop=_CallbackStop)


def test_soundcard_music_uses_realtime_when_backend_exists():
    item = _item()
    fake_sd = _fake_sounddevice()
    with (
        patch.dict("sys.modules", {"sounddevice": fake_sd}),
        patch("ancient_empires.audio.playback.OplRealtimeSource", return_value=_Source()) as source,
    ):
        assert play_audio_item_realtime(item, exe_path="game.exe")
    source.assert_called_once()
    assert _Stream.instances[-1].started


def test_realtime_raises_loudly_when_backend_missing_instead_of_silent_fallback():
    # sounddevice/numpy are hard deps and sound-card music needs the nuked_opl3
    # cffi backend (requirements.txt).  A missing one must raise, not silently
    # degrade to a different renderer.
    with patch.dict("sys.modules", {"sounddevice": None}):
        try:
            play_audio_item_realtime(_item(), exe_path="game.exe")
            assert False, "expected ImportError when sounddevice is missing"
        except ImportError:
            pass


def test_pc_speaker_source_preserves_tone_across_chunk_boundaries():
    item = _item()
    item = item.__class__(
        kind="pc-speaker-sfx",
        key=item.key,
        label=item.label,
        archive_name=item.archive_name,
        resource_index=item.resource_index,
        resource_type=item.resource_type,
        sound_id=1,
        offset=item.offset,
        length=4,
        data=bytes((0x01, 0x81, 0x0F, 0x00)),
    )
    source = PcSpeakerRealtimeSource(item, speed=1.0)
    first = source.read(64)
    second = source.read(64)
    assert np.any(first)
    assert np.any(second)


def test_pc_speaker_items_use_same_realtime_backend_when_available():
    item = _item().__class__(
        kind="pc-speaker-sfx",
        key="sfx",
        label="sfx",
        archive_name="AE000",
        resource_index=65,
        resource_type=0x44,
        sound_id=1,
        offset=0,
        length=4,
        data=bytes((0x01, 0x81, 0x0F, 0x00)),
    )
    fake_sd = _fake_sounddevice()
    with patch.dict("sys.modules", {"sounddevice": fake_sd}):
        assert play_audio_item_realtime(item, speed=1.0)
    assert _Stream.instances[-1].started
