from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ae_editor.audio.core import AudioItem
from ae_editor.audio.playback import temp_preview_wav


def _item() -> AudioItem:
    return AudioItem(
        kind="soundcard-music",
        key="AE000:054",
        label="AE000:054",
        archive_name="AE000",
        resource_index=54,
        resource_type=0,
        sound_id=None,
        offset=None,
        length=3,
        data=b"abc",
    )


def test_temp_preview_wav_reuses_content_addressed_cache():
    with TemporaryDirectory() as temp_dir:
        def render(_data, _exe, path, *, speed):
            Path(path).write_bytes(b"RIFF" + b"\0" * 64)
            return Path(path)

        with (
            patch("ae_editor.audio.playback.tempfile.gettempdir", return_value=temp_dir),
            patch("ae_editor.audio.playback.synthesize_soundcard_music_wav", side_effect=render) as synth,
        ):
            first = temp_preview_wav(_item(), speed=1.0, exe_path="missing.exe")
            second = temp_preview_wav(_item(), speed=1.0, exe_path="missing.exe")
            changed_speed = temp_preview_wav(_item(), speed=1.25, exe_path="missing.exe")

        assert first == second
        assert changed_speed != first
        assert synth.call_count == 2
