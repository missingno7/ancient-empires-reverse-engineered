from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import math
import os
import platform
import shutil
import struct
import tempfile
import wave

from ..constants import GAME_MASTER_TICK_HZ
from .gm import GM_PROGRAM_NAMES

SAMPLE_RATE = 44100
PIT_HZ = 1193180.0

# PC speaker / CAF1 SFX facts that are now considered stable:
#
# * AE000:065 is the event SFX bank used by CAF1/play_sound(id).
# * The leading 16-bit table in AE000:065 is a sound-id -> stream-offset table.
#   The first word 0x0096 is therefore the start of sound 0x00, not a PIT
#   divisor or a note table entry.
# * Normal note opcodes use the EXE music-style chromatic note mapping.
# * Direct-effect opcodes (?E) use the CA9B PIT arithmetic with a live divisor
#   base. CA9B reads the first word of the EXE's PIT divisor table at DS:17FC.
#   Keep it isolated here so that executable state is not mixed with resource
#   offsets.
PC_SPEAKER_STREAM_START = 0x0096
PC_SPEAKER_DIRECT_BASE_DIVISOR = 0x8E88
# The EXE advances audio from the same master timer/update cadence used by the
# game loop.  Keep preview speed adjustable, but make 1.0x the measured clock.
DEFAULT_PREVIEW_SPEED = 1.0

@dataclass(frozen=True)
class AudioItem:
    kind: str  # "pc-speaker-sfx", "pc-speaker-music", "soundcard-music", "raw"
    key: str
    label: str
    archive_name: str
    resource_index: int
    resource_type: int
    sound_id: int | None
    offset: int | None
    length: int
    data: bytes
    notes: str = ""


@dataclass(frozen=True)
class MusicChannelSummary:
    index: int
    is_rhythm: bool
    timbres: tuple[int, ...]
    expressions: tuple[int, ...]
    default_program: int | None
    event_count: int
    opl_instrument_id: int | None = None
    opl_config: int | None = None
    opl_voice_level: int | None = None


@dataclass(frozen=True)
class SoundCardMusicHeader:
    """AdLib/Sound Blaster metadata found before the bytecode streams.

    The first four words are stream offsets. Bytes 0x08..0x10 are nine OPL
    instrument ids consumed by the AdLib initialization path in the EXE. Bytes
    0x11..0x19 and 0x1A..0x22 are per-voice configuration/level hints.
    """

    offsets: tuple[int, ...]
    instrument_ids: tuple[int | None, ...]
    configs: tuple[int | None, ...]
    voice_levels: tuple[int | None, ...]


@dataclass(frozen=True)
class OplOperatorParams:
    """Decoded 13-word operator definition from the EXE OPL table.

    The game stores each operator as 13 little-endian words, but the OPL loader
    only uses the low byte of each word. Two operators plus two waveform words
    make one 0x38-byte instrument definition at DS:301A.
    """

    values: tuple[int, ...]
    waveform: int

    @property
    def ksl(self) -> int:
        return self.values[0] & 0x03

    @property
    def multiple(self) -> int:
        return self.values[1] & 0x0F

    @property
    def feedback_or_op_hint(self) -> int:
        return self.values[2] & 0x0F

    @property
    def attack(self) -> int:
        return self.values[3] & 0x0F

    @property
    def sustain_level(self) -> int:
        # ASM E324 writes register 0x80 as values[4] << 4 | values[7].
        return self.values[4] & 0x0F

    @property
    def sustain_enabled(self) -> bool:
        # This bit is the OPL envelope-generator type / sustain flag used in
        # register 0x20. It is not the sustain-level nibble.
        return bool(self.values[5])

    @property
    def decay(self) -> int:
        # ASM E2D6 writes register 0x60 as values[3] << 4 | values[6].
        return self.values[6] & 0x0F

    @property
    def release(self) -> int:
        return self.values[7] & 0x0F

    @property
    def total_level(self) -> int:
        return self.values[8] & 0x3F

    @property
    def tremolo(self) -> bool:
        return bool(self.values[9])

    @property
    def vibrato(self) -> bool:
        return bool(self.values[10])

    @property
    def key_scale_rate(self) -> bool:
        return bool(self.values[11])

    @property
    def carrier_sustain_hint(self) -> bool:
        return bool(self.values[12])

    def opl20(self) -> int:
        return ((0x80 if self.tremolo else 0) | (0x40 if self.vibrato else 0) |
                (0x20 if self.sustain_enabled else 0) | (0x10 if self.key_scale_rate else 0) |
                self.multiple)

    def opl40(self, *, volume_adjusted_tl: int | None = None) -> int:
        tl = self.total_level if volume_adjusted_tl is None else (volume_adjusted_tl & 0x3F)
        return ((self.ksl & 0x03) << 6) | tl

    def opl60(self) -> int:
        # ASM E2D6: attack nibble from values[3], decay nibble from values[6].
        return ((self.attack & 0x0F) << 4) | self.decay

    def opl80(self) -> int:
        # ASM E324: sustain-level nibble from values[4], release from values[7].
        return ((self.sustain_level & 0x0F) << 4) | self.release

    def ople0(self) -> int:
        return self.waveform & 0x03


@dataclass(frozen=True)
class OplInstrumentPatch:
    index: int
    modulator: OplOperatorParams
    carrier: OplOperatorParams

    @property
    def feedback(self) -> int:
        # The C0 register uses the second operator's byte 2 as feedback-ish
        # value in the EXE path; the low bit comes from byte 12 as the
        # additive/FM connection flag.
        return self.carrier.feedback_or_op_hint & 0x07

    @property
    def additive(self) -> bool:
        # In OPL terms: bit 0 of C0. False = FM/modulated, True = additive.
        return not self.carrier_sustain_disabled

    @property
    def carrier_sustain_disabled(self) -> bool:
        return bool(self.carrier.values[12])

    def oplc0(self) -> int:
        connection = 0 if self.carrier_sustain_disabled else 1
        return ((self.feedback & 0x07) << 1) | connection


@dataclass(frozen=True)
class SoundCardControlEvent:
    time_ticks: int
    kind: str  # "timbre" or "expression"
    value: int


def _u16(data: bytes, off: int) -> int:
    if off + 2 > len(data):
        return 0xFFFF
    return struct.unpack_from("<H", data, off)[0]


def _validated_event_offsets(data: bytes, max_count: int = 64) -> list[int]:
    """Return the confirmed CAF1/play_sound offsets from the event SFX bank.

    Type 0x44 resources are not all the same thing.  The common mistake is to
    treat every resource starting with 96 00 as a sound-effect offset table.
    For the real CAF1 bank (AE000:065), the first words form a valid monotonic
    table for play_sound ids 0..27.  For PC-speaker music resources the same
    96 00 prefix is an instrument/tone preamble and only the first stream at
    0x96 is meaningful.
    """
    if len(data) < 0x100:
        return []
    first = _u16(data, 0)
    if first != 0x0096 or first >= len(data):
        return []
    offsets: list[int] = []
    last = -1
    for i in range(max_count):
        off = _u16(data, i * 2)
        if not (first <= off < len(data)) or off < last:
            break
        # Real streams normally start with simple bytecode commands such as
        # 4D/4B/3D/0D or duration+pitch pairs like 1E/2E/3E/4E.
        if i > 0 and data[off] not in {0x4D, 0x0D, 0x1E, 0x2E, 0x3E, 0x4E, 0x5E, 0x6E, 0x7E, 0x8E}:
            break
        offsets.append(off)
        last = off
    return offsets if len(offsets) >= 8 else []


def looks_like_event_sfx_bank(data: bytes) -> bool:
    return bool(_validated_event_offsets(data))


def split_event_sfx_bank(data: bytes) -> list[tuple[int, int, bytes]]:
    offsets = _validated_event_offsets(data)
    items: list[tuple[int, int, bytes]] = []
    for i, off in enumerate(offsets):
        next_off = offsets[i + 1] if i + 1 < len(offsets) else len(data)
        if next_off > off:
            items.append((i, off, data[off:next_off]))
    return items


def looks_like_pc_speaker_resource(data: bytes) -> bool:
    # Music/effect resources with a PC-speaker style preamble start at 0x96,
    # but do NOT contain a valid event-SFX offset table.
    return len(data) > 0x96 and _u16(data, 0) == 0x0096 and not looks_like_event_sfx_bank(data)


def soundcard_music_offsets(data: bytes) -> list[int]:
    """Return channel/track offsets for the AdLib/SoundBlaster music format."""
    if len(data) < 16:
        return []
    first = _u16(data, 0)
    # Known music resources start near 0x23/0x24; the first few words are
    # channel offsets, then a small header/config area follows before stream 0.
    if not (0x10 <= first <= 0x40 and first < len(data)):
        return []
    offsets: list[int] = []
    last = -1
    for i in range(0, min(first // 2, 8)):
        off = _u16(data, i * 2)
        if not (first <= off <= len(data)) or off <= last:
            break
        offsets.append(off)
        last = off
    return offsets if len(offsets) >= 2 else []


def looks_like_soundcard_music(data: bytes) -> bool:
    return bool(soundcard_music_offsets(data))


def looks_like_high_score_table(data: bytes) -> bool:
    """Return True for the AE000:061/062 10x27-byte player/high-score tables.

    These records were once misidentified as sound-card patch banks. They are
    intentionally filtered out of the Audio Atlas now that the names in them are
    confirmed to be player/high-score data.
    """
    if len(data) != 270:
        return False
    records = [data[i:i + 27] for i in range(0, len(data), 27)]
    plausible = 0
    for rec in records:
        name = rec[:9].split(b"\0", 1)[0]
        if 1 <= len(name) <= 9 and all(32 <= b <= 126 for b in name):
            plausible += 1
    return plausible >= 2


EXE_AUDIO_DS_BASE = 0x0FA30
EXE_HEADER_SIZE = 0x200
OPL_PATCH_TABLE_DS_OFFSET = 0x301A
OPL_PATCH_STRIDE = 0x38
OPL_PATCH_COUNT = 64




@dataclass(frozen=True)
class OplRegisterWrite:
    time_ticks: int
    voice: int
    register: int
    value: int
    note: str = ""


OPL_VOICE_OPERATOR_SLOTS = (
    (0x00, 0x03), (0x01, 0x04), (0x02, 0x05),
    (0x08, 0x0B), (0x09, 0x0C), (0x0A, 0x0D),
    (0x10, 0x13), (0x11, 0x14), (0x12, 0x15),
)

OPL_MULTIPLIER_TABLE = (0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0,
                        8.0, 9.0, 10.0, 10.0, 12.0, 12.0, 15.0, 15.0)

# DEFA builds the runtime pitch tables consumed by E48A. For the default table,
# C5EA maps note index -> octave and C64A maps note index -> semitone. C6C3 holds
# the standard YM3812 FNUM row below; E48A writes it directly to A0/B0.
OPL_FNUM_TABLE = (0x157, 0x16B, 0x181, 0x198, 0x1B0, 0x1CA,
                  0x1E5, 0x202, 0x220, 0x241, 0x263, 0x287)

# The 9-voice AdLib render sits one octave above the raw bytecode pitch; the
# MIDI/PC-speaker path is unchanged and this applies only to the approximate
# AdLib WAV preview. The OPL trace/VGM path uses E48A's exact note-index mapping.
ADLIB_OPL_GLOBAL_TRANSPOSE = -12

# Single master gain applied equally to every OPL voice before the WAV mix is
# peak-normalized.  The AEPROG AdLib driver (DB60) routes every enabled voice
# through the same OPL path; the relative loudness between voices comes entirely
# from each instrument's carrier total-level and the header voice level (applied
# via carrier_tl), NOT from per-channel weighting.  Earlier previews damped the
# octave-stacked voices and nearly muted the third stream to match one capture,
# which removed the deep, full character the stacked voices are meant to create.
ADLIB_VOICE_MIX_GAIN = 0.11
ADLIB_PREVIEW_SOFT_LOWPASS_HZ = 0.0

# OPL operator self-feedback (register C0 bits 1..3, value 0..7).  Several music
# instruments use maximum feedback (e.g. AE000:054 ids 0F/0E/17 use 6..7), which
# turns the sine into a bright, gritty, noise-like timbre - this is what makes
# those voices sound "sampled/percussive" in the original.  True OPL feedback is
# a per-sample recursion (the operator modulates its own phase by the average of
# its last two outputs).  We approximate the steady-state feedback waveform with
# a few fixed-point iterations of y = wave(phase + beta*y), which is vectorizable
# and captures the harmonic enrichment.  beta scales with the feedback register.
OPL_FEEDBACK_BETA = 0.5
OPL_FEEDBACK_ITERS = 4


def _operator_init_registers(slot: int, op: OplOperatorParams, *, total_level_override: int | None = None) -> list[tuple[int, int]]:
    """Return the OPL register/value pairs that E1F2/E372/E2D6/E324/E44B emit."""
    return [
        (0x20 + slot, op.opl20()),
        (0x40 + slot, op.opl40(volume_adjusted_tl=total_level_override)),
        (0x60 + slot, op.opl60()),
        (0x80 + slot, op.opl80()),
        (0xE0 + slot, op.ople0()),
    ]


def _voice_adjusted_carrier_tl(header: SoundCardMusicHeader, voice: int, patch: OplInstrumentPatch) -> int:
    """Model D8F0's write to DS:301A + instrument*0x38 + 0x2A.

    Offset 0x2A is the low byte of second-operator word 8, i.e. the carrier
    total level used by E27B when writing OPL register 0x40+carrier_slot.
    """
    level = header.voice_levels[voice] if voice < len(header.voice_levels) else None
    if level is None:
        return patch.carrier.total_level
    return max(0, min(0x3F, 0x3F - (level & 0xFF) * 9))


def soundcard_music_opl_init_writes(data: bytes, exe_path: Path | str) -> list[OplRegisterWrite]:
    """Return the AdLib/OPL register writes used when a sound-card song starts.

    This mirrors the D8F0 -> DA66 -> E0C0/E1F2... initialization path enough to
    debug instruments without having to run the DOS binary.
    """
    header = soundcard_music_header(data)
    if header is None:
        return []
    table = load_opl_instrument_table(exe_path)
    writes: list[OplRegisterWrite] = []
    for voice, inst_id in enumerate(header.instrument_ids[:9]):
        if inst_id is None:
            continue
        patch = table.get(inst_id)
        if patch is None:
            continue
        mod_slot, car_slot = OPL_VOICE_OPERATOR_SLOTS[voice]
        carrier_tl = _voice_adjusted_carrier_tl(header, voice, patch)
        for reg, value in _operator_init_registers(mod_slot, patch.modulator):
            writes.append(OplRegisterWrite(0, voice, reg, value, f"voice {voice} inst {inst_id:02X} mod"))
        for reg, value in _operator_init_registers(car_slot, patch.carrier, total_level_override=carrier_tl):
            writes.append(OplRegisterWrite(0, voice, reg, value, f"voice {voice} inst {inst_id:02X} car"))
        writes.append(OplRegisterWrite(0, voice, 0xC0 + voice, patch.oplc0(), f"voice {voice} inst {inst_id:02X} C0"))
    return writes


def write_opl_register_trace_csv(data: bytes, exe_path: Path | str, path: Path | str) -> Path:
    path = Path(path)
    rows = ["time_ticks,voice,register,value,note"]
    for write in soundcard_music_opl_init_writes(data, exe_path):
        rows.append(f"{write.time_ticks},{write.voice},0x{write.register:02X},0x{write.value:02X},{write.note}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _opl_fnum_block_from_freq(freq: float) -> tuple[int, int]:
    """Convert a Hz frequency to YM3812 F-number/block fields.

    The game ultimately writes OPL A0/B0 registers through E48A.  The exact DOS
    code uses precomputed tables built at runtime, but the YM3812 relationship
    is stable enough to reproduce the same register layer for debugging/VGM
    export:

        freq ~= fnum * 49716 / 2 ** (20 - block)

    Choose the block with an in-range 10-bit fnum, preferring the normal OPL
    0x157..0x2AE-ish range to minimize rounding error.
    """
    if freq <= 0:
        return 0, 0
    best: tuple[float, int, int] | None = None
    for block in range(8):
        fnum = int(round(freq * (2 ** (20 - block)) / 49716.0))
        if not (0 <= fnum <= 0x3FF):
            continue
        # Prefer the central range used by normal OPL note tables, but allow
        # anything legal when very low/high notes need it.
        penalty = 0.0 if 0x100 <= fnum <= 0x3FF else 1000.0
        actual = fnum * 49716.0 / (2 ** (20 - block))
        err = abs(actual - freq) + penalty
        if best is None or err < best[0]:
            best = (err, block, fnum)
    if best is None:
        return 0x3FF, 7
    _err, block, fnum = best
    return fnum & 0x3FF, block & 0x07


def _opl_note_register_writes(voice: int, freq: float | None, *, key_on: bool) -> list[tuple[int, int]]:
    """Return A0/B0 writes for one OPL voice.

    Mirrors the useful part of E52A/E48A: E52A turns a voice off by writing B0
    then A0, and E48A writes A0 low fnum and B0 block/fnum-hi/key-on.  For note
    on we keep the A0/B0 order used by E48A.
    """
    if freq is None or not key_on:
        return [(0xB0 + voice, 0x00), (0xA0 + voice, 0x00)]
    fnum, block = _opl_fnum_block_from_freq(freq)
    return [
        (0xA0 + voice, fnum & 0xFF),
        (0xB0 + voice, 0x20 | ((block & 0x07) << 2) | ((fnum >> 8) & 0x03)),
    ]


def _opl_note_index_register_writes(voice: int, note_index: int, *, key_on: bool) -> list[tuple[int, int]]:
    """Return the exact default-table A0/B0 writes used by ASM E48A."""
    if not key_on:
        return [(0xB0 + voice, 0x00), (0xA0 + voice, 0x00)]
    note_index = max(0, min(0x5F, int(note_index)))
    block, semitone = divmod(note_index, 12)
    fnum = OPL_FNUM_TABLE[semitone]
    return [
        (0xA0 + voice, fnum & 0xFF),
        (0xB0 + voice, 0x20 | ((block & 0x07) << 2) | ((fnum >> 8) & 0x03)),
    ]


def _soundcard_freq_to_note_index(freq: float) -> int:
    """Undo the sound-card preview frequency mapping back to E48A's note index."""
    midi = int(round(69.0 + 12.0 * math.log2(freq / 440.0)))
    # _note_to_freq(..., pitch_mode="soundcard") maps raw index 0 to MIDI 24.
    return midi - 24


def soundcard_music_opl_full_writes(data: bytes, exe_path: Path | str, *, speed: float = DEFAULT_PREVIEW_SPEED) -> list[OplRegisterWrite]:
    """Return a pragmatic full-song OPL register trace for a sound-card song.

    The earlier CSV only emitted instrument initialization.  This adds the note
    layer: stream 0 drives voices 0..2, stream 1 drives 3..5, stream 2 drives
    6..8, with per-voice pitch offsets from the DAT header.  The trace is meant
    for debugging and VGM export; the exact YM3812 synthesis should be delegated
    to an OPL emulator/player rather than approximated by the atlas WAV synth.
    """
    header = soundcard_music_header(data)
    if header is None:
        return []
    writes: list[OplRegisterWrite] = []
    # Core AdLib setup seen around D99B/DA49/D9E1 in the EXE.
    writes.append(OplRegisterWrite(0, -1, 0x01, 0x20, "enable OPL waveform select"))
    writes.append(OplRegisterWrite(0, -1, 0x08, 0x00, "normal OPL mode"))
    writes.append(OplRegisterWrite(0, -1, 0xBD, 0x00, "melodic mode / rhythm off"))
    for voice in range(9):
        for reg, value in _opl_note_register_writes(voice, None, key_on=False):
            writes.append(OplRegisterWrite(0, voice, reg, value, f"voice {voice} initial off"))
    writes.extend(soundcard_music_opl_init_writes(data, exe_path))

    streams = _streams_from_resource(data)
    parsed = _parse_music_streams_synchronized(
        streams,
        [False for _ in streams],
        max_events=2400,
        pitch_mode="soundcard",
    )
    speed = max(0.10, min(8.0, float(speed)))

    for group, events in enumerate(parsed[:3]):
        pos_ticks = 0
        for freq, dur_seconds in events:
            event_ticks = max(1, int(round((dur_seconds * speed) / TICK_SECONDS)))
            voices = range(group * 3, min(group * 3 + 3, 9))
            if freq is None or freq < 0:
                for voice in voices:
                    for reg, value in _opl_note_register_writes(voice, None, key_on=False):
                        writes.append(OplRegisterWrite(pos_ticks, voice, reg, value, f"stream {group} rest/off"))
            else:
                for voice in voices:
                    # The real DB60 calls E52A immediately before E48A.
                    for reg, value in _opl_note_register_writes(voice, None, key_on=False):
                        writes.append(OplRegisterWrite(pos_ticks, voice, reg, value, f"voice {voice} retrigger off"))
                    cfg = header.configs[voice] if voice < len(header.configs) else 0
                    pitch_offset = 0 if cfg is None else (cfg - 0x100 if cfg >= 0x80 else cfg)
                    note_index = _soundcard_freq_to_note_index(freq) + pitch_offset
                    for reg, value in _opl_note_index_register_writes(voice, note_index, key_on=True):
                        writes.append(OplRegisterWrite(pos_ticks, voice, reg, value, f"stream {group} note voice {voice}"))
            pos_ticks += event_ticks
    writes.sort(key=lambda w: w.time_ticks)
    return writes


def write_opl_full_register_trace_csv(data: bytes, exe_path: Path | str, path: Path | str, *, speed: float = DEFAULT_PREVIEW_SPEED) -> Path:
    path = Path(path)
    rows = ["time_ticks,time_seconds,voice,register,value,note"]
    for write in soundcard_music_opl_full_writes(data, exe_path, speed=speed):
        seconds = write.time_ticks * TICK_SECONDS / max(0.10, min(8.0, float(speed)))
        rows.append(f"{write.time_ticks},{seconds:.6f},{write.voice},0x{write.register:02X},0x{write.value:02X},{write.note}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def write_opl_vgm(data: bytes, exe_path: Path | str, path: Path | str, *, speed: float = DEFAULT_PREVIEW_SPEED) -> Path:
    """Export a YM3812 VGM trace for use with an accurate OPL emulator/player.

    This is the most accurate output added so far: it does not try to fake FM
    synthesis in Python.  It emits the recovered YM3812 register writes so a VGM
    player can synthesize them with its own OPL core.
    """
    path = Path(path)
    writes = soundcard_music_opl_full_writes(data, exe_path, speed=speed)
    speed = max(0.10, min(8.0, float(speed)))
    sample_rate = 44100
    stream = bytearray()
    current_sample = 0
    total_sample = 0

    def emit_wait(samples: int) -> None:
        nonlocal current_sample
        samples = max(0, int(samples))
        while samples > 0:
            chunk = min(samples, 0xFFFF)
            stream.extend((0x61, chunk & 0xFF, (chunk >> 8) & 0xFF))
            current_sample += chunk
            samples -= chunk

    for w in writes:
        target_sample = int(round((w.time_ticks * TICK_SECONDS / speed) * sample_rate))
        if target_sample > current_sample:
            emit_wait(target_sample - current_sample)
        stream.extend((0x5A, w.register & 0xFF, w.value & 0xFF))
        total_sample = max(total_sample, current_sample)
    # Let the last note/release breathe a little; callers can trim in a DAW.
    emit_wait(int(sample_rate * 1.0))
    total_sample = current_sample
    stream.append(0x66)

    header_size = 0x100
    blob = bytearray(header_size)
    blob[0:4] = b"Vgm "
    # VGM version 1.51 with data offset and YM3812 clock field.
    struct.pack_into("<I", blob, 0x08, 0x00000151)
    struct.pack_into("<I", blob, 0x14, 0)                 # GD3 offset
    struct.pack_into("<I", blob, 0x18, total_sample)      # total samples
    struct.pack_into("<I", blob, 0x1C, 0)                 # loop offset
    struct.pack_into("<I", blob, 0x20, 0)                 # loop samples
    struct.pack_into("<I", blob, 0x24, 60)                # nominal rate
    struct.pack_into("<I", blob, 0x34, header_size - 0x34) # data offset
    struct.pack_into("<I", blob, 0x50, 3579545)           # YM3812 clock
    out = bytes(blob) + bytes(stream)
    # EOF offset is relative to 0x04.
    out = bytearray(out)
    struct.pack_into("<I", out, 0x04, len(out) - 4)
    path.write_bytes(bytes(out))
    return path


def synthesize_ym3812_wav(
    data: bytes,
    exe_path: Path | str,
    path: Path | str,
    *,
    speed: float = DEFAULT_PREVIEW_SPEED,
) -> Path:
    """Render sound-card music through a real YM3812 emulator.

    DOSBox Staging feeds AdLib register writes into an OPL emulator at the
    chip's native rate. ymfm-py gives the atlas the same register-level shape:
    the recovered AEPROG writes drive a YM3812 core instead of the lightweight
    approximation used by synthesize_adlib_like_wav.
    """
    try:
        import numpy as np  # type: ignore
        import ymfm  # type: ignore
    except Exception as exc:
        raise RuntimeError("Accurate YM3812 preview requires ymfm-py and numpy") from exc

    path = Path(path)
    writes = soundcard_music_opl_full_writes(data, exe_path, speed=speed)
    if not writes:
        return synthesize_wav(data, path, music=True, audio_kind="soundcard-music", speed=speed)

    speed = max(0.10, min(8.0, float(speed)))
    chip = ymfm.YM3812(clock=3579545)
    chip.reset()
    sample_rate = int(chip.sample_rate)
    current_sample = 0
    chunks = []

    def emit(samples: int) -> None:
        nonlocal current_sample
        if samples <= 0:
            return
        chunks.append(np.asarray(chip.generate(samples), dtype=np.int32).reshape(-1))
        current_sample += samples

    for write in writes:
        target_sample = int(round((write.time_ticks * TICK_SECONDS / speed) * sample_rate))
        emit(target_sample - current_sample)
        chip.write_address(write.register)
        chip.write_data(write.value)

    # Preserve the final release similarly to the VGM export.
    emit(sample_rate)
    pcm = np.concatenate(chunks) if chunks else np.zeros(1, dtype=np.int32)
    frames_bytes = pcm.clip(-32768, 32767).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(frames_bytes)
    return path


def synthesize_soundcard_music_wav(
    data: bytes,
    exe_path: Path | str,
    path: Path | str,
    *,
    speed: float = DEFAULT_PREVIEW_SPEED,
) -> Path:
    """Prefer chip-emulated sound-card music and retain the quick fallback."""
    try:
        return synthesize_ym3812_wav(data, exe_path, path, speed=speed)
    except RuntimeError:
        return synthesize_adlib_like_wav(data, exe_path, path, speed=speed)


def _opl_waveform(kind: int, phase: float) -> float:
    x = math.sin(phase)
    kind &= 0x03
    if kind == 0:
        return x
    if kind == 1:
        return max(0.0, x)
    if kind == 2:
        return abs(x) * 2.0 - 1.0
    # OPL2 waveform 3 is a quarter-ish sine family; this is intentionally only
    # a preview approximation, not a cycle-accurate YM3812 emulator.
    return max(0.0, math.sin(phase)) * 2.0 - 1.0


def _fb_waveform(kind: int, phase: float, beta: float) -> float:
    """Operator output with OPL-style self-feedback (scalar)."""
    if beta <= 0.0:
        return _opl_waveform(kind, phase)
    y = _opl_waveform(kind, phase)
    for _ in range(OPL_FEEDBACK_ITERS):
        y = _opl_waveform(kind, phase + beta * y)
    return y


def _opl_envelope(op: OplOperatorParams, t: float, dur: float) -> float:
    attack = 0.004 + (15 - op.attack) * 0.010
    decay = 0.018 + (15 - op.decay) * 0.018
    # OPL sustain level: 0 is loudest, 15 is quietest.
    sustain_amp = max(0.08, 1.0 - (op.sustain_level / 15.0) * 0.88)
    if t < attack:
        return t / max(attack, 1e-6)
    if t < attack + decay:
        f = (t - attack) / max(decay, 1e-6)
        return 1.0 + (sustain_amp - 1.0) * f
    # Apply a tiny tail fade at the end so bytecode note boundaries do not click.
    release = min(0.045 + (15 - op.release) * 0.003, max(0.0, dur * 0.35))
    if release > 0 and t > dur - release:
        return sustain_amp * max(0.0, (dur - t) / release)
    return sustain_amp


def _tl_to_amp(total_level: int) -> float:
    # YM3812 total-level attenuation is 0.75 dB per step.  Older atlas previews
    # used a deliberately gentle curve, which made modulators too loud and kept
    # high FM sidebands visible for the whole note.  Use the real attenuation
    # curve for AdLib matching; users can raise track gain after mixing.
    return 10.0 ** (-((total_level & 0x3F) * 0.75) / 20.0)


def _fm_render_note(patch: OplInstrumentPatch, freq: float, dur: float, sample_rate: int, *, carrier_tl: int | None = None) -> list[float]:
    n = max(1, int(round(dur * sample_rate)))
    out = [0.0] * n
    mod_mul = OPL_MULTIPLIER_TABLE[patch.modulator.multiple & 0x0F]
    car_mul = OPL_MULTIPLIER_TABLE[patch.carrier.multiple & 0x0F]
    mod_amp = _tl_to_amp(patch.modulator.total_level)
    car_amp = _tl_to_amp(patch.carrier.total_level if carrier_tl is None else carrier_tl)
    # A rough FM index. High modulator TL means quieter modulator, lower index.
    fm_index = 0.4 + 6.0 * mod_amp
    mod_beta = patch.feedback * OPL_FEEDBACK_BETA
    mod_phase = 0.0
    car_phase = 0.0
    mod_step = 2.0 * math.pi * freq * mod_mul / sample_rate
    car_step = 2.0 * math.pi * freq * car_mul / sample_rate
    for i in range(n):
        t = i / sample_rate
        env = _opl_envelope(patch.carrier, t, dur)
        # Both OPL operators have their own envelope.  A previous approximation
        # applied only the carrier envelope and left the modulator at a constant
        # strength, which produced bright, clean high-frequency sidebands that
        # are not present in the in-game capture.
        mod_env = _opl_envelope(patch.modulator, t, dur)
        mod_wave = _fb_waveform(patch.modulator.waveform, mod_phase, mod_beta)
        m = mod_wave * mod_env
        if patch.additive:
            c = 0.45 * mod_wave * mod_amp * mod_env + _opl_waveform(patch.carrier.waveform, car_phase) * car_amp
        else:
            c = _opl_waveform(patch.carrier.waveform, car_phase + fm_index * m)
            c *= car_amp
        out[i] = c * env
        mod_phase += mod_step
        car_phase += car_step
    return out



def _fm_render_note_numpy(patch: OplInstrumentPatch, freq: float, dur: float, sample_rate: int, *, carrier_tl: int | None = None):
    """Vectorized version of _fm_render_note used when numpy is available."""
    try:
        import numpy as np  # type: ignore
    except Exception:
        return _fm_render_note(patch, freq, dur, sample_rate, carrier_tl=carrier_tl)
    n = max(1, int(round(dur * sample_rate)))
    t = np.arange(n, dtype=np.float64) / float(sample_rate)
    mod_mul = OPL_MULTIPLIER_TABLE[patch.modulator.multiple & 0x0F]
    car_mul = OPL_MULTIPLIER_TABLE[patch.carrier.multiple & 0x0F]
    mod_amp = _tl_to_amp(patch.modulator.total_level)
    car_amp = _tl_to_amp(patch.carrier.total_level if carrier_tl is None else carrier_tl)
    fm_index = 0.4 + 6.0 * mod_amp
    mod_phase = 2.0 * math.pi * freq * mod_mul * t
    car_phase = 2.0 * math.pi * freq * car_mul * t

    def wave_np(kind: int, phase):
        x = np.sin(phase)
        kind &= 0x03
        if kind == 0:
            return x
        if kind == 1:
            return np.maximum(0.0, x)
        if kind == 2:
            return np.abs(x) * 2.0 - 1.0
        return np.maximum(0.0, x) * 2.0 - 1.0

    def fb_wave_np(kind: int, phase, beta: float):
        if beta <= 0.0:
            return wave_np(kind, phase)
        y = wave_np(kind, phase)
        for _ in range(OPL_FEEDBACK_ITERS):
            y = wave_np(kind, phase + beta * y)
        return y

    attack = 0.004 + (15 - patch.carrier.attack) * 0.010
    decay = 0.018 + (15 - patch.carrier.decay) * 0.018
    sustain_amp = max(0.08, 1.0 - (patch.carrier.sustain_level / 15.0) * 0.88)
    env = np.empty(n, dtype=np.float64)
    if attack > 0:
        attack_mask = t < attack
        env[attack_mask] = t[attack_mask] / attack
    else:
        attack_mask = np.zeros(n, dtype=bool)
    decay_mask = (t >= attack) & (t < attack + decay)
    if decay > 0:
        f = (t[decay_mask] - attack) / decay
        env[decay_mask] = 1.0 + (sustain_amp - 1.0) * f
    sustain_mask = ~(attack_mask | decay_mask)
    env[sustain_mask] = sustain_amp
    release = min(0.020 + (15 - patch.carrier.release) * 0.004, max(0.0, dur * 0.35))
    if release > 0:
        rel_mask = t > dur - release
        env[rel_mask] = sustain_amp * np.maximum(0.0, (dur - t[rel_mask]) / release)

    # Use the modulator's own envelope as the FM-index envelope.  Without this
    # the atlas preview is much brighter than the AdLib capture because the
    # modulating operator never decays.
    mod_attack = 0.004 + (15 - patch.modulator.attack) * 0.010
    mod_decay = 0.018 + (15 - patch.modulator.decay) * 0.018
    mod_sustain_amp = max(0.08, 1.0 - (patch.modulator.sustain_level / 15.0) * 0.88)
    mod_env = np.empty(n, dtype=np.float64)
    if mod_attack > 0:
        mod_attack_mask = t < mod_attack
        mod_env[mod_attack_mask] = t[mod_attack_mask] / mod_attack
    else:
        mod_attack_mask = np.zeros(n, dtype=bool)
    mod_decay_mask = (t >= mod_attack) & (t < mod_attack + mod_decay)
    if mod_decay > 0:
        f = (t[mod_decay_mask] - mod_attack) / mod_decay
        mod_env[mod_decay_mask] = 1.0 + (mod_sustain_amp - 1.0) * f
    mod_sustain_mask = ~(mod_attack_mask | mod_decay_mask)
    mod_env[mod_sustain_mask] = mod_sustain_amp
    mod_release = min(0.020 + (15 - patch.modulator.release) * 0.004, max(0.0, dur * 0.35))
    if mod_release > 0:
        mod_rel_mask = t > dur - mod_release
        mod_env[mod_rel_mask] = mod_sustain_amp * np.maximum(0.0, (dur - t[mod_rel_mask]) / mod_release)

    mod_beta = patch.feedback * OPL_FEEDBACK_BETA
    mod_wave = fb_wave_np(patch.modulator.waveform, mod_phase, mod_beta)
    m = mod_wave * mod_env
    if patch.additive:
        out = 0.45 * mod_wave * mod_amp * mod_env + wave_np(patch.carrier.waveform, car_phase) * car_amp
    else:
        out = wave_np(patch.carrier.waveform, car_phase + fm_index * m) * car_amp
    return out * env

def synthesize_adlib_like_wav(
    data: bytes,
    exe_path: Path | str,
    path: Path | str,
    *,
    speed: float = DEFAULT_PREVIEW_SPEED,
) -> Path:
    """Render a pragmatic AdLib-like preview using extracted EXE FM patches.

    This is not a cycle-accurate YM3812 emulator. It is an atlas/audition render
    that uses the real instrument table, the music header's patch ids and the
    same bytecode timing/note parser as MIDI/WAV preview.
    """
    path = Path(path)
    header = soundcard_music_header(data)
    if header is None:
        return synthesize_wav(data, path, music=True, audio_kind="soundcard-music", speed=speed)
    table = load_opl_instrument_table(exe_path)
    streams = _streams_from_resource(data)
    # The AdLib driver does not treat the three resource streams as only three
    # final voices. ASM DB60 maps each stream group to a triad of OPL voices:
    #   stream 0 -> voices 0,1,2
    #   stream 1 -> voices 3,4,5
    #   stream 2 -> voices 6,7,8
    # Bytes 0x11..0x19 copied to DS:CA62..CA6A are pitch offsets for those
    # nine voices.  Earlier previews rendered only one voice per stream, which
    # lost most of the organ/plucked FM texture heard in the real capture.
    rhythm_flags = [False for _ in streams]
    parsed = _parse_music_streams_synchronized(streams, rhythm_flags, max_events=2200, pitch_mode="soundcard")
    speed = max(0.10, min(8.0, float(speed)))
    parsed = [[(freq, dur / speed) for freq, dur in events] for events in parsed]
    total_duration = max(sum(d for _f, d in ev) for ev in parsed)
    total_samples = max(1, int(round(total_duration * SAMPLE_RATE)) + 1)
    try:
        import numpy as np  # type: ignore
        mix = np.zeros(total_samples, dtype=np.float64)
        use_numpy = True
    except Exception:
        np = None  # type: ignore
        mix = [0.0] * total_samples
        use_numpy = False

    def transpose_freq(freq: float, semitones: int | None) -> float:
        # Header values are unsigned in the known resources, but keep signed
        # handling for future music records if a composer uses downward offsets.
        if semitones is None:
            offset = ADLIB_OPL_GLOBAL_TRANSPOSE
        else:
            offset = semitones - 0x100 if semitones >= 0x80 else semitones
            offset += ADLIB_OPL_GLOBAL_TRANSPOSE
        return freq * (2.0 ** (offset / 12.0))

    for group, events in enumerate(parsed[:3]):
        for local_voice in range(3):
            voice = group * 3 + local_voice
            if voice >= 9:
                continue
            inst_id = header.instrument_ids[voice] if voice < len(header.instrument_ids) else None
            patch = table.get(inst_id) if inst_id is not None else None
            if patch is None:
                continue
            carrier_tl = _voice_adjusted_carrier_tl(header, voice, patch)
            pitch_offset = header.configs[voice] if voice < len(header.configs) else 0
            pos = 0
            # Every enabled voice sounds at its real OPL level (carrier_tl is
            # already applied inside _fm_render_note), so all nine voices share
            # one master gain.  No per-channel weighting and no octave damping -
            # the full octave stack is what gives the music its depth.
            amp = ADLIB_VOICE_MIX_GAIN
            for freq, dur in events:
                n = max(1, int(round(dur * SAMPLE_RATE)))
                if freq is None:
                    pos += n
                    continue
                if freq < 0:
                    # Reserved for future rhythm-mode decoding. AE000:054's
                    # third stream is percussive by composition, but the AdLib
                    # code still routes it through ordinary OPL voices.
                    pos += n
                    continue
                note_freq = transpose_freq(freq, pitch_offset)
                if use_numpy:
                    note = _fm_render_note_numpy(patch, note_freq, dur, SAMPLE_RATE, carrier_tl=carrier_tl)
                    end = min(total_samples, pos + len(note))
                    if end > pos:
                        mix[pos:end] += amp * note[:end - pos]
                else:
                    note = _fm_render_note(patch, note_freq, dur, SAMPLE_RATE, carrier_tl=carrier_tl)
                    for j, v in enumerate(note):
                        if pos + j >= total_samples:
                            break
                        mix[pos + j] += amp * v
                pos += n
    if use_numpy:
        # Gentle spectral calibration for the atlas WAV preview.  The real OPL
        # chip/player should be used for exact synthesis; this only prevents the
        # Python approximation from sounding much brighter than the capture.
        if ADLIB_PREVIEW_SOFT_LOWPASS_HZ and len(mix) > 8:
            freqs = np.fft.rfftfreq(len(mix), 1.0 / SAMPLE_RATE)
            spec = np.fft.rfft(mix)
            filt = 1.0 / np.sqrt(1.0 + (freqs / ADLIB_PREVIEW_SOFT_LOWPASS_HZ) ** 4)
            mix = np.fft.irfft(spec * filt, n=len(mix))
        peak = float(max(0.01, abs(mix).max()))
        scale = 0.92 / peak if peak > 0.92 else 1.0
        pcm = (mix * scale).clip(-1.0, 1.0)
        frames_bytes = (pcm * 32767.0).astype('<i2').tobytes()
    else:
        peak = max(0.01, max(abs(v) for v in mix))
        scale = 0.92 / peak if peak > 0.92 else 1.0
        frames = bytearray()
        for v in mix:
            sample = int(max(-1.0, min(1.0, v * scale)) * 32767)
            frames += struct.pack("<h", sample)
        frames_bytes = bytes(frames)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(frames_bytes)
    return path

def _exe_file_offset_for_ds(ds_offset: int) -> int:
    return EXE_HEADER_SIZE + EXE_AUDIO_DS_BASE + ds_offset


def parse_opl_instrument_patch(raw: bytes, index: int) -> OplInstrumentPatch | None:
    if len(raw) < OPL_PATCH_STRIDE:
        return None
    words = struct.unpack("<28H", raw[:OPL_PATCH_STRIDE])
    mod_values = tuple(word & 0xFF for word in words[:13])
    car_values = tuple(word & 0xFF for word in words[13:26])
    mod_wave = words[26] & 0x03
    car_wave = words[27] & 0x03
    return OplInstrumentPatch(
        index=index,
        modulator=OplOperatorParams(mod_values, mod_wave),
        carrier=OplOperatorParams(car_values, car_wave),
    )


def load_opl_instrument_table(exe_path: Path | str, *, count: int = OPL_PATCH_COUNT) -> dict[int, OplInstrumentPatch]:
    """Extract the internal AdLib/OPL instrument table from AEPROG.EXE.

    ASM evidence: D8F0 multiplies the music header instrument id by 0x38 and
    adds DS:301A. DA66 then reads two 13-word operator blocks plus two waveform
    words and programs the OPL registers through C898.
    """
    blob = Path(exe_path).read_bytes()
    base = _exe_file_offset_for_ds(OPL_PATCH_TABLE_DS_OFFSET)
    out: dict[int, OplInstrumentPatch] = {}
    for index in range(count):
        off = base + index * OPL_PATCH_STRIDE
        patch = parse_opl_instrument_patch(blob[off:off + OPL_PATCH_STRIDE], index)
        if patch is None:
            break
        out[index] = patch
    return out


def describe_opl_patch(patch: OplInstrumentPatch) -> str:
    def op_summary(name: str, op: OplOperatorParams) -> str:
        flags = "".join(flag for flag, active in [("T", op.tremolo), ("V", op.vibrato), ("S", op.sustain_enabled), ("K", op.key_scale_rate)] if active) or "-"
        return (
            f"{name}: 20={op.opl20():02X} 40={op.opl40():02X} 60={op.opl60():02X} "
            f"80={op.opl80():02X} E0={op.ople0():02X} "
            f"mul={op.multiple:X} TL={op.total_level:02X} ADSR={op.attack:X}/{op.decay:X}/{op.sustain_level:X}/{op.release:X} flags={flags}"
        )
    return (
        f"OPL patch {patch.index:02X}: C0={patch.oplc0():02X}; "
        + op_summary("mod", patch.modulator)
        + "; "
        + op_summary("car", patch.carrier)
    )


def describe_opl_patches_for_music(data: bytes, exe_path: Path | str | None) -> str:
    header = soundcard_music_header(data)
    if header is None or exe_path is None:
        return ""
    try:
        table = load_opl_instrument_table(exe_path)
    except Exception as exc:
        return f"Unable to extract EXE OPL table: {exc}"
    ids = [value for value in header.instrument_ids if value is not None]
    seen = []
    for value in ids:
        if value not in seen:
            seen.append(value)
    parts = []
    for value in seen[:8]:
        patch = table.get(value)
        if patch is not None:
            parts.append(describe_opl_patch(patch))
    if not parts:
        return "No matching OPL patches found in EXE table."
    suffix = "" if len(seen) <= 8 else f"; +{len(seen) - 8} more instrument ids"
    return "EXE OPL table DS:301A / stride 0x38: " + " | ".join(parts) + suffix


def soundcard_music_header(data: bytes) -> SoundCardMusicHeader | None:
    """Parse the AdLib/Sound Blaster pre-stream header of a music resource.

    Layout observed in AE000 sound-card music records:
      0x00..0x07  four little-endian stream offsets
      0x08..0x10  nine OPL instrument ids, FF for unused voice
      0x11..0x19  nine voice config bytes
      0x1A..0x22  nine voice level/routing bytes
    The EXE's AdLib path reads these bytes before playback and combines the
    ids with its internal OPL patch table, so this is the first real FM mapping
    layer in the DAT files.
    """
    offsets = soundcard_music_offsets(data)
    if len(offsets) < 1 or len(data) < 0x23 or offsets[0] < 0x23:
        return None

    def clean(values: bytes) -> tuple[int | None, ...]:
        return tuple(None if value == 0xFF else value for value in values[:9])

    return SoundCardMusicHeader(
        offsets=tuple(offsets),
        instrument_ids=clean(data[0x08:0x11]),
        configs=clean(data[0x11:0x1A]),
        voice_levels=clean(data[0x1A:0x23]),
    )


def describe_soundcard_music_header(data: bytes) -> str:
    header = soundcard_music_header(data)
    if header is None:
        return "no AdLib/Sound Blaster header detected"

    def fmt(values: tuple[int | None, ...]) -> str:
        return " ".join("FF" if value is None else f"{value:02X}" for value in values)

    return (
        "AdLib/Sound Blaster header detected: "
        f"stream offsets={', '.join('0x%04X' % o for o in header.offsets)}; "
        f"OPL instrument ids={fmt(header.instrument_ids)}; "
        f"voice cfg={fmt(header.configs)}; voice level={fmt(header.voice_levels)}"
    )


def soundcard_music_preamble(data: bytes) -> bytes:
    """Return bytes between the channel-offset table and stream 0."""
    offsets = soundcard_music_offsets(data)
    if not offsets:
        return b""
    table_len = len(offsets) * 2
    first_stream = offsets[0]
    if first_stream <= table_len:
        return b""
    return data[table_len:first_stream]


KNOWN_MUSIC_BASES = {
    ("AE000", 49): "startup/title intro music (confirmed: D26C pushes resource 0x31)",
    ("AE000", 53): "menu/interstitial music (confirmed D5F9 call with 0x35)",
    ("AE000", 67): "game/menu music (confirmed D5F9 call with 0x43)",
    ("AE000", 69): "game/menu music (confirmed D5F9 call with 0x45)",
}


def _music_pair_note(archive_name: str, resource_index: int, *, soundcard: bool) -> str:
    base_index = resource_index - 1 if soundcard else resource_index
    base = KNOWN_MUSIC_BASES.get((archive_name, base_index))
    if base:
        return base
    if soundcard:
        return f"PSG/Tandy-like sound-card half of music pair {base_index:03d}/{resource_index:03d}"
    return f"PC-speaker half of music pair {resource_index:03d}/{resource_index + 1:03d}"


def build_audio_atlas(project) -> list[AudioItem]:
    items: list[AudioItem] = []
    for archive_name, archive in sorted(project.archives.items()):
        for res in archive.resources:
            if not res.ok or res.rtype != 0x44:
                continue
            data = res.decoded
            if looks_like_high_score_table(data):
                # Confirmed player/high-score tables (AE000:061/062), not audio.
                continue
            if looks_like_event_sfx_bank(data):
                offsets = _validated_event_offsets(data)
                for sound_id, off, chunk in split_event_sfx_bank(data):
                    items.append(AudioItem(
                        kind="pc-speaker-sfx",
                        key=f"pc-speaker-sfx:{archive_name}:{res.index}:{sound_id}",
                        label=f"play_sound {sound_id:02d} / 0x{sound_id:02X}",
                        archive_name=archive_name,
                        resource_index=res.index,
                        resource_type=res.rtype,
                        sound_id=sound_id,
                        offset=off,
                        length=len(chunk),
                        data=chunk,
                        notes=f"Confirmed play_sound/event_07 PC-speaker SFX from AE000:065 ({len(offsets)} ids).",
                    ))
            elif looks_like_pc_speaker_resource(data):
                items.append(AudioItem(
                    kind="pc-speaker-music",
                    key=f"pc-speaker-music:{archive_name}:{res.index}",
                    label=f"PC speaker music {archive_name}:{res.index:03d}",
                    archive_name=archive_name,
                    resource_index=res.index,
                    resource_type=res.rtype,
                    sound_id=None,
                    offset=0x96,
                    length=len(data) - 0x96,
                    data=data,
                    notes=_music_pair_note(archive_name, res.index, soundcard=False) + "; PC-speaker music stream.",
                ))
            elif looks_like_soundcard_music(data):
                offs = soundcard_music_offsets(data)
                items.append(AudioItem(
                    kind="soundcard-music",
                    key=f"soundcard-music:{archive_name}:{res.index}",
                    label=f"Sound-card music mix {archive_name}:{res.index:03d}",
                    archive_name=archive_name,
                    resource_index=res.index,
                    resource_type=res.rtype,
                    sound_id=None,
                    offset=offs[0],
                    length=len(data),
                    data=data,
                    notes=_music_pair_note(archive_name, res.index, soundcard=True) + "; complete sound-card music mix; FM patches come from the resource header and EXE OPL table.",
                ))
    order = {"pc-speaker-sfx": 0, "pc-speaker-music": 1, "soundcard-music": 2}
    return sorted(items, key=lambda item: (order.get(item.kind, 9), item.archive_name, item.resource_index, item.sound_id or 0))


NOTE_BASE_MIDI = 36  # C2-ish; the original uses a PIT divisor table, this is the closest musical preview.
TICK_SECONDS = 1.0 / GAME_MASTER_TICK_HZ
MAX_EVENT_SECONDS = 1.50


def _midi_to_freq(midi: float) -> float:
    return 440.0 * (2.0 ** ((midi - 69.0) / 12.0))


def _direct_pitch_to_freq(pitch: int, octave_shift: int = 0) -> float | None:
    """Decode the CAF1/PC-speaker direct-pitch opcode ``0x?E``.

    Disassembly of the one-shot SFX routine at ``CA9B`` shows this is not a
    MIDI-like pitch value.  The engine does roughly::

        dx = arg << 7
        dx = -dx
        ax = WORD PTR ds:17fc + dx
        ax >>= high_nibble
        program PIT channel 2 with ax

    The subtraction deliberately wraps in 16-bit arithmetic.  That wraparound is
    what makes effects such as 0x06/0x07/0x0E sound buzzy/noise-like instead of
    like a clean ascending musical scale.
    """
    if pitch <= 0:
        return None
    base_divisor = PC_SPEAKER_DIRECT_BASE_DIVISOR
    divisor = (base_divisor - ((pitch & 0xFF) << 7)) & 0xFFFF
    divisor >>= max(0, octave_shift)
    if divisor < 2:
        return None
    freq = PIT_HZ / divisor
    # The real PIT/speaker path does not turn high divisors into rests. Keep
    # high-frequency events so jump/laser sweeps stay continuous.
    return freq if freq >= 20.0 else None


def _chromatic_note_to_freq(note: int, octave: int, *, transpose: int = 0) -> float:
    # EXE sound-card path C384 uses note-1 + octave*12. Real-game captures
    # confirm that CAF1 normal-note SFX should follow this musical mapping; the
    # AE000:065 leading word table is only a stream offset table.
    midi = NOTE_BASE_MIDI + octave * 12 + (note - 1) + transpose
    return _midi_to_freq(max(24, min(108, midi)))


def _note_to_freq(note: int, octave: int, *, transpose: int = 0, pitch_mode: str = "musical") -> float | None:
    # Normal note events are musical bytecode events, not raw PIT divisors.
    # Real-game capture of AE000:054 confirms that the sound-card branch is one
    # octave lower than the older generic preview: byte 35 01 should sound as E4,
    # not E5. Keep PC speaker previews on the old base and shift only the
    # sound-card/Tandy-style branch.
    if pitch_mode == "soundcard":
        transpose -= 12
    return _chromatic_note_to_freq(note, octave, transpose=transpose)


def _is_probable_rhythm_stream(stream: bytes, stream_no: int | None = None) -> bool:
    """Heuristic for the AdLib rhythm/noise voice.

    The third stream in the title music (AE000:054 @0x0397) is dominated by
    commands like ``1A 01`` and ``1C 01``.  Interpreting those as ordinary
    melodic notes makes MIDI channel 2 sound wrong.  In the real AdLib driver
    this is very likely a percussion/rhythm timbre selected through the 5D/6D
    instrument commands, not a melody voice.
    """
    pairs = [(stream[i], stream[i + 1]) for i in range(0, len(stream) - 1, 2)]
    note_ops = [op for op, _arg in pairs if 1 <= (op & 0x0F) <= 12]
    if len(note_ops) < 12:
        return False
    rhythm_ops = [op for op in note_ops if (op >> 4) == 1 and (op & 0x0F) in {10, 12}]
    if len(rhythm_ops) / max(1, len(note_ops)) >= 0.65:
        return True
    # Fallback: in confirmed music resources the third non-empty channel is the
    # suspicious rhythm/noise channel.  Keep this weaker than the content test so
    # single-channel exports are classified by data, not by position alone.
    if stream_no is not None and stream_no >= 2 and len(set(op & 0x0F for op in note_ops)) <= 3:
        return True
    return False


def _is_release_timbre(selector: int) -> bool:
    # AE000:054 uses 5D 23 at note boundaries where the real driver points the
    # PSG envelope reader at a release/silent sequence. Treat it as articulation,
    # not as a new MIDI instrument.
    return selector in {0x23}


def _gm_program_for_timbre(selector: int | None, stream_no: int, *, rhythm: bool = False) -> int | None:
    if rhythm:
        return None
    if selector == 0x02:
        return 8   # Celesta / bell-like lead, zero-based GM program.
    if selector == 0x06:
        return 34  # Electric Bass (picked), zero-based GM program.
    # Sensible defaults for resources/channels without an explicit non-release
    # 5D selector before their first note.
    if stream_no == 0:
        return 8
    if stream_no == 1:
        return 34
    return 80      # Lead 1 (square) fallback for old exports.


def _expression_for_aux_byte(value: int) -> int:
    # 6D is a live auxiliary driver byte. It is not tempo and not pitch. MIDI has
    # no direct PSG-envelope equivalent, so expose it as a gentle expression hint
    # rather than making it dominate dynamics.
    if value <= 0x0F:
        return max(48, min(127, 127 - value * 4))
    return max(48, min(127, value))


def scan_soundcard_control_events(
    data: bytes,
    *,
    initial_base_ticks: int | None = None,
    music: bool = True,
    max_events: int = 2400,
) -> list[SoundCardControlEvent]:
    """Return timed 5D/6D controls from one sound-card music stream.

    The EXE handlers at C5B3/C5C6 do not program an AdLib OPL instrument. 5D
    stores an envelope/timbre pointer and 6D stores an auxiliary byte that later
    affects PSG-style latched writes. For MIDI we keep these as timed metadata
    and translate them conservatively to program/expression events.
    """
    controls: list[SoundCardControlEvent] = []
    i = 0
    time_ticks = 0
    base_ticks = initial_base_ticks if initial_base_ticks is not None else _shared_initial_base_ticks([data], music=music)
    bend_ticks = 0
    effect_ticks = 1
    seen = 0
    while i + 1 < len(data) and seen < max_events:
        op = data[i]
        arg = data[i + 1]
        i += 2
        if op == 0xFF and arg == 0xFF:
            break
        lo = op & 0x0F
        hi = (op >> 4) & 0x0F
        if lo == 0x0F:
            break
        if lo == 0x0D:
            if hi in (1, 2):
                if arg:
                    delta = (base_ticks * arg + 50) // 100
                    bend_ticks = delta if hi == 1 else -delta
                else:
                    bend_ticks = 0
            elif hi == 3:
                effect_ticks = max(1, arg)
            elif hi == 4:
                base_ticks = max(1, arg * 4)
                bend_ticks = 0
            elif hi == 5:
                controls.append(SoundCardControlEvent(time_ticks, "timbre", arg))
            elif hi == 6:
                controls.append(SoundCardControlEvent(time_ticks, "expression", arg))
            continue
        if lo == 0x0E:
            time_ticks += max(1, effect_ticks)
            seen += 1
            continue
        if lo == 0 or 1 <= lo <= 12:
            time_ticks += _duration_ticks_from_game_code(arg, base_ticks, bend_ticks)
            seen += 1
    return controls


def _drum_note_for_op(op: int) -> int:
    lo = op & 0x0F
    # General MIDI percussion map on channel 10.  These are only labels for
    # exported MIDI; the game uses AdLib timbres/noise, not GM drums.
    if lo == 10:
        return 42  # closed hi-hat / tick
    if lo == 12:
        return 46  # open hi-hat / brighter tick
    if lo in (5, 6):
        return 38  # snare-ish accent
    if lo in (1, 3):
        return 36  # kick-ish accent
    return 42


def _seconds_from_ticks(ticks: int, *, minimum: float | None = None) -> float:
    seconds = max(1, ticks) * TICK_SECONDS
    if minimum is not None:
        seconds = max(minimum, seconds)
    return min(MAX_EVENT_SECONDS, seconds)


def parse_game_audio_drum_stream(
    data: bytes,
    *,
    max_events: int = 2400,
    music: bool = True,
    initial_base_ticks: int | None = None,
) -> list[tuple[int | None, float]]:
    """Parse a stream as rhythm/percussion events for MIDI/WAV preview.

    This uses the same timing/control commands as the melodic parser, but keeps
    the original low-nibble note identity so we can map it to GM percussion
    instead of converting it into a wrong melodic pitch.
    """
    events: list[tuple[int | None, float]] = []
    i = 0
    base_ticks = initial_base_ticks if initial_base_ticks is not None else _shared_initial_base_ticks([data], music=music)
    bend_ticks = 0
    gate_ticks = 6
    gate_enabled = True
    effect_ticks = 1
    while i + 1 < len(data) and len(events) < max_events:
        op = data[i]
        arg = data[i + 1]
        i += 2
        if op == 0xFF and arg == 0xFF:
            break
        lo = op & 0x0F
        hi = (op >> 4) & 0x0F
        if lo == 0x0F:
            break
        if lo == 0x0D:
            if hi == 0:
                if arg:
                    gate_enabled = True
                    gate_ticks = max(1, arg)
                else:
                    gate_enabled = False
            elif hi in (1, 2):
                if arg:
                    delta = (base_ticks * arg + 50) // 100
                    bend_ticks = delta if hi == 1 else -delta
                else:
                    bend_ticks = 0
            elif hi == 3:
                effect_ticks = max(1, arg)
            elif hi == 4:
                base_ticks = max(1, arg * 4)
                bend_ticks = 0
            continue
        if lo == 0x0E:
            events.append((42, _seconds_from_ticks(effect_ticks)))
            continue
        dur = _duration_from_game_code(arg, base_ticks, bend_ticks)
        if lo == 0:
            events.append((None, dur))
        elif 1 <= lo <= 12:
            events.append((_drum_note_for_op(op), dur))
    return events or [(42, 0.08)]

def _leading_base_ticks(stream: bytes) -> int | None:
    """Return a leading 4D tempo/base-duration command, if present.

    In the EXE, command low-nibble D with high nibble 4 stores arg*4 into the
    global base-duration word (music: ds:1788, one-shot SFX: ds:1e84).  In
    multi-channel music, this is global state, not per-track state.  A common
    pattern is that channel 0 begins with ``4D 64`` and the other channels
    immediately rely on that value without repeating it.
    """
    for i in range(0, min(len(stream) - 1, 64), 2):
        op, arg = stream[i], stream[i + 1]
        if op == 0xFF and arg == 0xFF:
            return None
        if (op & 0x0F) == 0x0D and (op >> 4) == 4:
            return max(1, arg * 4)
        # Stop once real note data begins; later 4D commands are mid-song
        # tempo changes, not initial calibration.
        if (op & 0x0F) not in (0x0D,):
            break
    return None


def _shared_initial_base_ticks(streams: list[bytes], *, music: bool) -> int:
    for stream in streams:
        base = _leading_base_ticks(stream)
        if base is not None:
            return base
    # Music channels that do not carry their own leading 4D normally inherit
    # the title/theme default 4D 64 from another channel.  CAF1 SFX historically
    # start from 4D 4B unless a stream overrides it.
    return (0x64 if music else 0x4B) * 4


def _duration_ticks_from_game_code(code: int, base_ticks: int, bend_ticks: int = 0) -> int:
    ticks = max(1, base_ticks + bend_ticks)
    if code & 0x80:
        # ASM C9A4 masks bit 7 from AL, then jumps directly to the final store
        # of BX. BX still contains the full base duration; the remaining bits
        # are ignored for timing on this branch.
        pass
    else:
        ticks >>= (code & 0x07)
        if code & 0x08:
            ticks += max(1, ticks // 2)
    return max(1, ticks)


def _duration_from_game_code(code: int, base_ticks: int, bend_ticks: int = 0) -> float:
    """Decode the second byte roughly like routines C3DB/C9A4."""
    return _seconds_from_ticks(_duration_ticks_from_game_code(code, base_ticks, bend_ticks))


def _append_pc_speaker_event(
    events: list[tuple[float | None, float]],
    freq: float | None,
    ticks: int,
    *,
    gate_enabled: bool,
    gate_ticks: int,
) -> None:
    """Append a note/rest while modelling the EXE's per-channel gate cutoff.

    Routine C3DB stores the full event duration in ``[si+179c]``.  During the
    timer update, routine C27D calls C6B9 (speaker off) near the end of a note
    unless command ``0D 00`` has disabled this gate behaviour.  The comparison
    is against ``gate_ticks - 1`` remaining ticks, so the tail becomes silent.

    This matters for short SFX: the bytecode can describe a long logical note
    but only keep the PC speaker audible for the attack portion.
    """
    ticks = max(1, ticks)
    if freq is None or not gate_enabled or gate_ticks <= 1 or ticks <= gate_ticks:
        events.append((freq, _seconds_from_ticks(ticks)))
        return
    audible = max(1, ticks - (gate_ticks - 1))
    silent = ticks - audible
    events.append((freq, _seconds_from_ticks(audible)))
    if silent:
        events.append((None, _seconds_from_ticks(silent)))


def _streams_from_resource(data: bytes) -> list[bytes]:
    if looks_like_soundcard_music(data):
        offs = soundcard_music_offsets(data)
        streams: list[bytes] = []
        for i, off in enumerate(offs):
            end = offs[i + 1] if i + 1 < len(offs) else len(data)
            chunk = data[off:end]
            if chunk and chunk[:2] != b"\xff\xff":
                streams.append(chunk)
        return streams or [data]
    if looks_like_pc_speaker_resource(data):
        return [data[0x96:]]
    return [data]


def parse_game_audio_stream(
    data: bytes,
    *,
    max_events: int = 2400,
    music: bool = False,
    initial_base_ticks: int | None = None,
    transpose: int = 0,
    pitch_mode: str = "pc_speaker",
) -> list[tuple[float | None, float]]:
    """Parse the Ancient Empires audio bytecode into preview note events.

    Important EXE findings used here:
      * low nibble 1..12 = note
      * low nibble 0    = rest
      * low nibble D    = control command
      * low nibble E    = direct pitch / effect tone
      * low nibble F    = end or loop marker

    Music has *global* tempo/base-duration state.  In the title resource, for
    example, channel 0 starts with ``4D 64`` but the other channels do not; the
    EXE still uses that same base duration for all channels.  Older atlas builds
    parsed every channel independently, which made tracks drift or feel like
    they had different speeds.
    """
    events: list[tuple[float | None, float]] = []
    i = 0
    base_ticks = initial_base_ticks if initial_base_ticks is not None else _shared_initial_base_ticks([data], music=music)
    bend_ticks = 0
    gate_ticks = 6
    gate_enabled = True
    effect_ticks = 1
    while i + 1 < len(data) and len(events) < max_events:
        op = data[i]
        arg = data[i + 1]
        i += 2
        if op == 0xFF and arg == 0xFF:
            break
        lo = op & 0x0F
        hi = (op >> 4) & 0x0F
        if lo == 0x0F:
            # Real engine can loop/retrigger depending on a global flag.  For
            # atlas preview stop at the first terminator to avoid infinite audio.
            break
        if lo == 0x0D:
            if hi == 0:
                # sustain/gate flag. arg=0 is common in music and means the
                # channel should not be cut short by the normal gate counter.
                if arg:
                    gate_enabled = True
                    gate_ticks = max(1, arg)
                else:
                    gate_enabled = False
            elif hi in (1, 2):
                # Tempo bend as percentage of current base duration.  Routine
                # c567/ca51 computes round(base*arg/100), positive for 1D and
                # negative for 2D.
                if arg:
                    delta = (base_ticks * arg + 50) // 100
                    bend_ticks = delta if hi == 1 else -delta
                else:
                    bend_ticks = 0
            elif hi == 3:
                # Direct-pitch/effect note length.  CAF1 initializes this to
                # one master tick; commands such as 3D xx override it.
                effect_ticks = max(1, arg)
            elif hi == 4:
                # Global base duration: arg * 4 ticks.
                base_ticks = max(1, arg * 4)
                bend_ticks = 0
            elif hi == 5:
                # Music: instrument/envelope sequence selector (c5b3), not
                # tempo.  Older preview builds incorrectly treated this as a
                # gate/timing command, which made some channels feel wrong.
                pass
            elif hi == 6:
                # Music: auxiliary volume/timbre byte (c5c6).
                pass
            continue
        if lo == 0x0E:
            dur = _seconds_from_ticks(effect_ticks)
            events.append((_direct_pitch_to_freq(arg, hi), dur))
            continue
        ticks = _duration_ticks_from_game_code(arg, base_ticks, bend_ticks)
        if lo == 0:
            events.append((None, _seconds_from_ticks(ticks)))
        elif 1 <= lo <= 12:
            _append_pc_speaker_event(
                events,
                _note_to_freq(lo, hi, transpose=transpose, pitch_mode=pitch_mode),
                ticks,
                gate_enabled=gate_enabled,
                gate_ticks=gate_ticks,
            )
    if not events:
        events = [(440.0, 0.08), (None, 0.08), (660.0, 0.08)]
    return events


# Backward-compatible name used by the GUI/export code.
def parse_note_pairs(
    data: bytes,
    *,
    music: bool = False,
    max_events: int = 800,
    initial_base_ticks: int | None = None,
    pitch_mode: str = "pc_speaker",
) -> list[tuple[float | None, float]]:
    return parse_game_audio_stream(
        data,
        max_events=max_events,
        music=music,
        initial_base_ticks=initial_base_ticks,
        pitch_mode=pitch_mode,
    )


@dataclass
class _AudioStreamCursor:
    stream_no: int
    data: bytes
    rhythm: bool
    pc: int = 0
    time_ticks: int = 0
    ended: bool = False
    gate_ticks: int = 6
    gate_enabled: bool = True
    effect_ticks: int = 1
    events: list[tuple[float | None, float]] = field(default_factory=list)


def _parse_music_streams_synchronized(
    streams: list[bytes],
    rhythm_flags: list[bool],
    *,
    max_events: int = 1800,
    pitch_mode: str = "pc_speaker",
) -> list[list[tuple[float | None, float]]]:
    """Parse multi-channel music with the EXE's shared timing state.

    Music command handlers around C3DB/C501 use global base-duration and bend
    words (`ds:1788`/`ds:178a`) while each channel keeps its own stream pointer
    and remaining note length.  Parsing each stream independently lets later
    `4D`/`1D`/`2D` changes affect only one exported channel, which makes MIDI
    tracks drift.  This small event scheduler processes the earliest channel
    next, matching the game loop's channel order for tied times.
    """
    base_ticks = _shared_initial_base_ticks(streams, music=True)
    bend_ticks = 0
    cursors = [
        _AudioStreamCursor(i, stream, rhythm_flags[i] if i < len(rhythm_flags) else False)
        for i, stream in enumerate(streams)
    ]

    total_events = 0
    while total_events < max_events * max(1, len(cursors)):
        active = [cursor for cursor in cursors if not cursor.ended]
        if not active:
            break
        cursor = min(active, key=lambda item: (item.time_ticks, item.stream_no))
        emitted = False
        while cursor.pc + 1 < len(cursor.data):
            op = cursor.data[cursor.pc]
            arg = cursor.data[cursor.pc + 1]
            cursor.pc += 2
            if op == 0xFF and arg == 0xFF:
                cursor.ended = True
                break
            lo = op & 0x0F
            hi = (op >> 4) & 0x0F
            if lo == 0x0F:
                cursor.ended = True
                break
            if lo == 0x0D:
                if hi == 0:
                    if arg:
                        cursor.gate_enabled = True
                        cursor.gate_ticks = max(1, arg)
                    else:
                        cursor.gate_enabled = False
                elif hi in (1, 2):
                    if arg:
                        delta = (base_ticks * arg + 50) // 100
                        bend_ticks = delta if hi == 1 else -delta
                    else:
                        bend_ticks = 0
                elif hi == 3:
                    cursor.effect_ticks = max(1, arg)
                elif hi == 4:
                    base_ticks = max(1, arg * 4)
                    bend_ticks = 0
                continue

            if lo == 0x0E:
                ticks = cursor.effect_ticks
                if cursor.rhythm:
                    freq: float | None = -42.0
                else:
                    freq = _direct_pitch_to_freq(arg, hi)
            else:
                ticks = _duration_ticks_from_game_code(arg, base_ticks, bend_ticks)
                if lo == 0:
                    freq = None
                elif 1 <= lo <= 12:
                    freq = -float(_drum_note_for_op(op)) if cursor.rhythm else _note_to_freq(lo, hi, pitch_mode=pitch_mode)
                else:
                    continue
            if lo == 0x0E or freq is None or freq < 0:
                cursor.events.append((freq, _seconds_from_ticks(ticks)))
            else:
                _append_pc_speaker_event(
                    cursor.events,
                    freq,
                    ticks,
                    gate_enabled=cursor.gate_enabled,
                    gate_ticks=cursor.gate_ticks,
                )
            cursor.time_ticks += max(1, ticks)
            total_events += 1
            emitted = True
            break
        if not emitted and cursor.pc + 1 >= len(cursor.data):
            cursor.ended = True

    for cursor in cursors:
        if not cursor.events:
            cursor.events.append((-42.0, 0.08) if cursor.rhythm else (440.0, 0.08))
    return [cursor.events for cursor in cursors]


def _events_to_absolute_spans(events: list[tuple[float | None, float]], rate: float) -> list[tuple[float | None, int, int]]:
    spans: list[tuple[float | None, int, int]] = []
    pos = 0.0
    for freq, dur in events:
        start = int(round(pos * rate))
        pos += max(0.0, dur)
        end = max(start + 1, int(round(pos * rate)))
        spans.append((freq, start, end))
    return spans


def _pitch_mode_from_audio_kind(kind: str | None, data: bytes, *, music: bool) -> str:
    if kind == "soundcard-music":
        return "soundcard"
    if kind in {"pc-speaker-sfx", "pc-speaker-music"}:
        return "musical"
    # Auto mode for callers that pass raw bytes without an atlas item kind.
    if music and looks_like_soundcard_music(data):
        return "soundcard"
    return "musical"


def synthesize_wav(data: bytes, path: Path | str, *, music: bool = False, speed: float = DEFAULT_PREVIEW_SPEED, audio_kind: str | None = None) -> Path:
    path = Path(path)
    streams = _streams_from_resource(data)
    pitch_mode = _pitch_mode_from_audio_kind(audio_kind, data, music=music)
    shared_base = _shared_initial_base_ticks(streams, music=music)
    rhythm_flags: list[bool] = []
    for stream_no, s in enumerate(streams):
        rhythm_flags.append(music and _is_probable_rhythm_stream(s, stream_no if len(streams) > 1 else None))
    if music and len(streams) > 1:
        parsed = _parse_music_streams_synchronized(streams, rhythm_flags, max_events=1800, pitch_mode=pitch_mode)
    else:
        parsed = []
        for stream_no, s in enumerate(streams):
            is_rhythm = rhythm_flags[stream_no]
            if is_rhythm:
                drum_events = parse_game_audio_drum_stream(s, max_events=1800, music=music, initial_base_ticks=shared_base)
                # Store drum note numbers in the freq slot with a negative sentinel.
                parsed.append([((-float(note) if note is not None else None), dur) for note, dur in drum_events])
            else:
                parsed.append(parse_note_pairs(
                    s,
                    music=music,
                    max_events=1800 if music else 5000,
                    initial_base_ticks=shared_base,
                    pitch_mode=pitch_mode,
                ))
    speed = max(0.10, min(8.0, float(speed)))
    parsed = [[(freq, dur / speed) for freq, dur in events] for events in parsed]
    # Render/mix streams.
    total_duration = max(sum(d for _f, d in ev) for ev in parsed)
    total_samples = max(1, int(round(total_duration * SAMPLE_RATE)) + 1)
    mix = [0.0] * total_samples
    for track_no, events in enumerate(parsed):
        phase = 0.0
        amp = 0.22 / max(1, len(parsed))
        for freq, start, end in _events_to_absolute_spans(events, SAMPLE_RATE):
            n = end - start
            if freq is not None:
                if freq < 0:
                    # Rhythm channel: short deterministic noise/tick burst, then
                    # silence for the rest of the event duration so timing stays
                    # intact but it does not become a wrong sustained melody.
                    burst = min(n, max(1, int(0.035 * SAMPLE_RATE)))
                    seed = int(-freq) * 1103515245 + track_no * 12345
                    for j in range(burst):
                        if start + j >= total_samples:
                            break
                        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
                        mix[start + j] += amp * (1.0 if (seed & 0x4000) else -1.0)
                else:
                    # Keep oscillator phase continuous across adjacent events.
                    # Resetting phase at every 1-tick ?E event made SFX 0x00
                    # develop audible zipper/click breaks that are stronger than
                    # the in-game PC speaker impression.
                    step = 2.0 * math.pi * freq / SAMPLE_RATE
                    for j in range(n):
                        if start + j >= total_samples:
                            break
                        # Square-ish tone is closer to PC speaker than sine.
                        mix[start + j] += amp * (1.0 if math.sin(phase) >= 0 else -1.0)
                        phase += step
            if end >= total_samples:
                break
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        frames = bytearray()
        for v in mix:
            s = int(max(-1.0, min(1.0, v)) * 32767)
            frames += struct.pack("<h", s)
        wf.writeframes(bytes(frames))
    return path


def _midi_varlen(value: int) -> bytes:
    value = max(0, int(value))
    buf = [value & 0x7F]
    value >>= 7
    while value:
        buf.append(0x80 | (value & 0x7F))
        value >>= 7
    return bytes(reversed(buf))


def _pitch_to_midi(freq: float | None, fallback_pitch: int = 60) -> int:
    if freq is None or freq <= 0:
        return fallback_pitch
    midi = int(round(69 + 12 * math.log2(freq / 440.0)))
    return max(24, min(108, midi))


def describe_music_channels(data: bytes, *, audio_kind: str | None = None) -> list[MusicChannelSummary]:
    """Return channel/timbre metadata used by the audio-atlas MIDI audition UI."""
    streams = _streams_from_resource(data)
    shared_base = _shared_initial_base_ticks(streams, music=True)
    rhythm_flags = [
        _is_probable_rhythm_stream(stream, stream_no if len(streams) > 1 else None)
        for stream_no, stream in enumerate(streams)
    ]
    pitch_mode = _pitch_mode_from_audio_kind(audio_kind, data, music=True)
    parsed = _parse_music_streams_synchronized(streams, rhythm_flags, max_events=1800, pitch_mode=pitch_mode) if len(streams) > 1 else []
    out: list[MusicChannelSummary] = []
    for stream_no, stream in enumerate(streams[:8]):
        is_rhythm = rhythm_flags[stream_no]
        controls = scan_soundcard_control_events(stream, initial_base_ticks=shared_base, music=True)
        timbres = tuple(dict.fromkeys(event.value for event in controls if event.kind == "timbre"))
        expressions = tuple(dict.fromkeys(event.value for event in controls if event.kind == "expression"))
        first_timbre = next((value for value in timbres if not _is_release_timbre(value)), None)
        default_program = _gm_program_for_timbre(first_timbre, stream_no, rhythm=is_rhythm)
        if len(streams) > 1:
            event_count = len(parsed[stream_no]) if stream_no < len(parsed) else 0
        else:
            event_count = 0
        header = soundcard_music_header(data) if len(streams) > 1 else None
        opl_id = header.instrument_ids[stream_no] if header and stream_no < len(header.instrument_ids) else None
        opl_cfg = header.configs[stream_no] if header and stream_no < len(header.configs) else None
        opl_level = header.voice_levels[stream_no] if header and stream_no < len(header.voice_levels) else None
        out.append(MusicChannelSummary(stream_no, is_rhythm, timbres, expressions, default_program, event_count, opl_id, opl_cfg, opl_level))
    return out


def _midi_event_ticks(events: list[tuple[float | None, float]], ticks_per_second: float) -> list[tuple[float | None, int, int]]:
    out: list[tuple[float | None, int, int]] = []
    pos = 0.0
    for freq, dur in events:
        start = int(round(pos * ticks_per_second))
        pos += max(0.0, dur)
        end = max(start + 1, int(round(pos * ticks_per_second)))
        out.append((freq, start, end))
    return out


def write_midi(
    data: bytes,
    path: Path | str,
    *,
    speed: float = DEFAULT_PREVIEW_SPEED,
    audio_kind: str | None = None,
    channel_programs: dict[int, int | None] | None = None,
) -> Path:
    path = Path(path)
    streams = _streams_from_resource(data)
    ticks_per_quarter = 96

    tracks: list[bytes] = []
    tempo_track = bytearray()
    tempo_track += b"\x00\xFF\x51\x03\x07\xA1\x20"  # 120 bpm
    tempo_track += b"\x00\xFF\x2F\x00"
    tracks.append(bytes(tempo_track))

    pitch_mode = _pitch_mode_from_audio_kind(audio_kind, data, music=True)
    shared_base = _shared_initial_base_ticks(streams, music=True)
    rhythm_flags = [
        _is_probable_rhythm_stream(stream, stream_no if len(streams) > 1 else None)
        for stream_no, stream in enumerate(streams)
    ]
    if len(streams) > 1:
        parsed_streams = _parse_music_streams_synchronized(streams, rhythm_flags, max_events=1800, pitch_mode=pitch_mode)
    else:
        parsed_streams = []
        for stream_no, stream in enumerate(streams):
            if rhythm_flags[stream_no]:
                drum_events = parse_game_audio_drum_stream(stream, max_events=1800, music=True, initial_base_ticks=shared_base)
                parsed_streams.append([((-float(note) if note is not None else None), dur) for note, dur in drum_events])
            else:
                parsed_streams.append(parse_game_audio_stream(
                    stream,
                    max_events=1800,
                    music=True,
                    initial_base_ticks=shared_base,
                    pitch_mode=pitch_mode,
                ))
    speed = max(0.10, min(8.0, float(speed)))
    parsed_streams = [[(freq, dur / speed) for freq, dur in events] for events in parsed_streams]
    ticks_per_second = ticks_per_quarter * 2
    for stream_no, stream in enumerate(streams[:8]):
        is_rhythm = rhythm_flags[stream_no]
        channel = 9 if is_rhythm else (stream_no % 15)
        tr = bytearray()
        timed_events: list[tuple[int, int, bytes]] = []

        controls = scan_soundcard_control_events(stream, initial_base_ticks=shared_base, music=True)
        first_timbre = next((event.value for event in controls if event.kind == "timbre" and not _is_release_timbre(event.value)), None)
        if channel_programs is not None and stream_no in channel_programs:
            initial_program = channel_programs[stream_no]
        else:
            initial_program = _gm_program_for_timbre(first_timbre, stream_no, rhythm=is_rhythm)
        if initial_program is not None:
            timed_events.append((0, 0, bytes([0xC0 | channel, max(0, min(127, int(initial_program)))])))

        for control in controls:
            midi_tick = int(round((control.time_ticks * TICK_SECONDS / speed) * ticks_per_second))
            if control.kind == "timbre":
                if _is_release_timbre(control.value):
                    # Release/silent PSG envelope marker; the note parser already
                    # handles timing, so do not convert this into a GM program.
                    continue
                # 5D is an internal envelope/timbre selector, not a reliable
                # General MIDI program-change stream. Keep export instruments
                # stable unless the user explicitly changes them in the atlas UI.
                continue
            elif control.kind == "expression" and not is_rhythm:
                timed_events.append((midi_tick, 1, bytes([0xB0 | channel, 11, _expression_for_aux_byte(control.value)])))

        note_spans = _midi_event_ticks(parsed_streams[stream_no], ticks_per_second)
        if is_rhythm:
            for freq, start, end in note_spans:
                if freq is None:
                    continue
                note = int(-freq) if freq < 0 else _pitch_to_midi(freq)
                audible_ticks = max(1, min(end - start, int(ticks_per_quarter * 0.10)))
                timed_events.append((start, 2, bytes([0x90 | channel, note, 80])))
                timed_events.append((start + audible_ticks, 3, bytes([0x80 | channel, note, 0])))
        else:
            for freq, start, end in note_spans:
                if freq is None:
                    continue
                note = _pitch_to_midi(freq)
                timed_events.append((start, 2, bytes([0x90 | channel, note, 80])))
                timed_events.append((end, 3, bytes([0x80 | channel, note, 0])))

        timed_events.sort(key=lambda item: (item[0], item[1]))
        last_tick = 0
        for tick, _priority, payload in timed_events:
            tr += _midi_varlen(tick - last_tick) + payload
            last_tick = tick
        track_end = note_spans[-1][2] if note_spans else last_tick
        tr += _midi_varlen(max(0, track_end - last_tick)) + b"\xFF\x2F\x00"
        tracks.append(bytes(tr))

    header = b"MThd" + struct.pack(">IHHH", 6, 1 if len(tracks) > 1 else 0, len(tracks), ticks_per_quarter)
    body = bytearray()
    for tr in tracks:
        body += b"MTrk" + struct.pack(">I", len(tr)) + tr
    path.write_bytes(header + bytes(body))
    return path

