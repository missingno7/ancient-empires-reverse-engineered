"""Smoke tests for the bundled Nuked-OPL3 cffi backend.

These are skipped automatically when the C extension has not been built
(``python -m nuked_opl3._ffi_build``).  They are the quickest way to confirm a
fresh build is wired up correctly.
"""
from __future__ import annotations

import array

import pytest

nuked_opl3 = pytest.importorskip("nuked_opl3")

if not getattr(nuked_opl3, "is_available", lambda: False)():
    pytest.skip("nuked_opl3 C extension not built", allow_module_level=True)

from nuked_opl3 import OPL3, OPL_NATIVE_RATE


def _i16(buf: bytes) -> array.array:
    a = array.array("h")
    a.frombytes(buf)
    return a


def test_silence_is_silent():
    chip = OPL3(sample_rate=OPL_NATIVE_RATE)
    assert chip.sample_rate == OPL_NATIVE_RATE
    samples = _i16(chip.generate_mono(256))
    assert len(samples) == 256
    assert max(abs(s) for s in samples) == 0


def test_keyed_note_produces_tone():
    chip = OPL3(sample_rate=OPL_NATIVE_RATE)
    # Minimal single-voice patch: fast attack, audible carrier, then key-on.
    for reg, val in [
        (0x20, 0x01), (0x23, 0x01),   # MULT=1 for op0/op1 of channel 0
        (0x40, 0x10), (0x43, 0x00),   # modest mod level, carrier full
        (0x60, 0xF0), (0x63, 0xF0),   # fast attack, slow decay
        (0x80, 0x77), (0x83, 0x77),   # sustain/release
        (0xC0, 0x01),                 # connection
        (0xA0, 0x98), (0xB0, 0x31),   # F-num/block + key-on
    ]:
        chip.write(reg, val)
    samples = _i16(chip.generate_mono(OPL_NATIVE_RATE // 10))  # 100 ms
    assert max(abs(s) for s in samples) > 1000  # clearly audible


def test_mono_is_left_of_stereo():
    chip = OPL3(sample_rate=OPL_NATIVE_RATE)
    for reg, val in [(0x40, 0x00), (0xC0, 0x01), (0xA0, 0x98), (0xB0, 0x31)]:
        chip.write(reg, val)
    stereo = _i16(chip.generate_stereo(64))
    # re-create a fresh chip with identical writes for the mono comparison
    chip2 = OPL3(sample_rate=OPL_NATIVE_RATE)
    for reg, val in [(0x40, 0x00), (0xC0, 0x01), (0xA0, 0x98), (0xB0, 0x31)]:
        chip2.write(reg, val)
    mono = _i16(chip2.generate_mono(64))
    assert len(stereo) == 128 and len(mono) == 64
    assert list(mono) == list(stereo[0::2])
