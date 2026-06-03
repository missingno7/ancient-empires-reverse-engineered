"""Tests for the OPL register-trace -> MIDI converter (write_opl_trace_midi)."""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from ancient_empires.audio.core import (
    _hz_to_fractional_midi,
    _opl_carrier_tl_to_velocity,
    _opl_fnum_block_to_hz,
    _opl_register_channel_op,
    build_audio_atlas,
    write_opl_trace_midi,
)
from ancient_empires.project import AncientEmpiresProject

EXE = Path("game_data/AEPROG.EXE")
DATS = [Path("game_data/AE000.DAT"), Path("game_data/AE001.DAT")]
_HAVE_GAME = EXE.exists() and all(d.exists() for d in DATS)


def _read_vlq(buf: bytes, pos: int) -> tuple[int, int]:
    value = 0
    while True:
        byte = buf[pos]
        pos += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, pos


def _parse_tracks(buf: bytes):
    assert buf[:4] == b"MThd"
    fmt, ntrk, division = struct.unpack(">HHH", buf[8:14])
    pos = 14
    tracks = []
    for _ in range(ntrk):
        assert buf[pos:pos + 4] == b"MTrk"
        length = struct.unpack(">I", buf[pos + 4:pos + 8])[0]
        tracks.append(buf[pos + 8:pos + 8 + length])
        pos += 8 + length
    return fmt, division, tracks


def _scan(track: bytes):
    pos = 0
    status = 0
    on = off = wheels = 0
    active: set[int] = set()
    malformed = 0
    while pos < len(track):
        _dt, pos = _read_vlq(track, pos)
        if track[pos] & 0x80:
            status = track[pos]
            pos += 1
        elif status < 0x80:
            malformed += 1
            break
        hi = status & 0xF0
        if hi == 0x90:
            note, vel = track[pos], track[pos + 1]
            pos += 2
            if vel > 0:
                on += 1
                active.add(note)
            else:
                off += 1
                active.discard(note)
        elif hi == 0x80:
            off += 1
            active.discard(track[pos])
            pos += 2
        elif hi == 0xE0:
            wheels += 1
            pos += 2
        elif hi in (0xB0,):
            pos += 2
        elif hi == 0xC0:
            pos += 1
        elif status == 0xFF:
            pos += 1
            length, pos = _read_vlq(track, pos)
            pos += length
        else:
            malformed += 1
            break
    return {"on": on, "off": off, "wheels": wheels, "hanging": len(active), "malformed": malformed}


def test_opl_fnum_and_note_helpers():
    # A4 region: FNum 0x244 block 4 ~ 440 Hz on OPL2.
    hz = _opl_fnum_block_to_hz(0x244, 4)
    assert 430 < hz < 450
    # Pitch rises with FNum and doubles with each block.
    assert _opl_fnum_block_to_hz(0x244, 5) == pytest.approx(hz * 2)
    assert abs(_hz_to_fractional_midi(440.0) - 69.0) < 1e-6
    assert _hz_to_fractional_midi(0.0) == 0.0
    # Carrier TL: 0 is loudest, 0x3F near-silent, monotonic.
    assert _opl_carrier_tl_to_velocity(0) == 127
    assert _opl_carrier_tl_to_velocity(0x3F) < _opl_carrier_tl_to_velocity(0x10)


def test_opl_register_channel_op_mapping():
    # Operator-layout: low slots 0..5 -> op0 of ch0,1,2 then op1 of ch0,1,2.
    assert _opl_register_channel_op(0x40) == (0, 0)  # ch0 modulator
    assert _opl_register_channel_op(0x43) == (0, 1)  # ch0 carrier
    assert _opl_register_channel_op(0x45) == (2, 1)  # ch2 carrier
    assert _opl_register_channel_op(0x46) is None    # gap slot
    assert _opl_register_channel_op(0x52) == (8, 0)  # ch8 modulator (0x12 slot)


@pytest.mark.skipif(not _HAVE_GAME, reason="game data not present")
def test_trace_midi_is_well_formed_and_balanced(tmp_path):
    proj = AncientEmpiresProject(EXE, DATS)
    items = [a for a in build_audio_atlas(proj) if a.kind == "soundcard-music"]
    assert items
    for item in items:
        out = tmp_path / f"{item.resource_index}.mid"
        write_opl_trace_midi(item.data, EXE, out)
        fmt, division, tracks = _parse_tracks(out.read_bytes())
        assert fmt == 1
        assert division == 96
        assert len(tracks) >= 2  # tempo + >=1 voice
        for track in tracks[1:]:
            stats = _scan(track)
            assert stats["malformed"] == 0
            assert stats["hanging"] == 0          # every note is released
            assert stats["on"] == stats["off"]    # balanced
            assert stats["wheels"] >= stats["on"]  # microtonal bend per note-on
