from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import os
import platform
import shutil
import struct
import subprocess
import tempfile
import wave

SAMPLE_RATE = 22050
PIT_HZ = 1193180.0
# The EXE advances audio from its timer/update loop.  In-game calibration is
# still approximate, but PC-speaker music currently matches the real game much
# better around 1.75x than the older 2.25x preview.
DEFAULT_PREVIEW_SPEED = 1.75

@dataclass(frozen=True)
class AudioItem:
    kind: str  # "pc-speaker-sfx", "pc-speaker-music", "soundcard-music", "soundcard-channel", "soundcard-patch", "raw"
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


def looks_like_soundcard_patch(data: bytes) -> bool:
    # AE000:061/062 contain instrument/driver-ish names (BLAKE, Viktor) and a
    # compact binary body.  Keep them visible as raw resources instead of trying
    # to synthesize them as songs.
    if len(data) < 32:
        return False
    head = data[:16]
    return any(name in head for name in (b"BLAKE", b"Viktor"))


KNOWN_MUSIC_BASES = {
    ("AE000", 49): "startup/title intro music (confirmed: D26C pushes resource 0x31)",
    ("AE000", 53): "menu/interstitial music candidate (confirmed D5F9 call with 0x35)",
    ("AE000", 67): "game/menu music candidate (confirmed D5F9 call with 0x43)",
    ("AE000", 69): "game/menu music candidate (confirmed D5F9 call with 0x45)",
}


def _music_pair_note(archive_name: str, resource_index: int, *, soundcard: bool) -> str:
    base_index = resource_index - 1 if soundcard else resource_index
    base = KNOWN_MUSIC_BASES.get((archive_name, base_index))
    if base:
        return base
    if soundcard:
        return f"sound-card half of music pair {base_index:03d}/{resource_index:03d}"
    return f"PC-speaker half of music pair {resource_index:03d}/{resource_index + 1:03d}"


def build_audio_atlas(project) -> list[AudioItem]:
    items: list[AudioItem] = []
    for archive_name, archive in sorted(project.archives.items()):
        for res in archive.resources:
            if not res.ok or res.rtype != 0x44:
                continue
            data = res.decoded
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
                        notes=f"CAF1/event_07 play_sound stream from confirmed AE000:065 SFX bank; {len(offsets)} ids found. Disassembly shows CAF1 uses the PC-speaker path (PIT channel 2 / ports 0x42 and 0x61); no separate AdLib/Sound Blaster SFX bank has been confirmed yet.",
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
                    notes=_music_pair_note(archive_name, res.index, soundcard=False) + "; 0x96 is the stream offset used by the EXE for PC-speaker music.",
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
                    notes=_music_pair_note(archive_name, res.index, soundcard=True) + f"; AdLib/SoundBlaster music resource. The first words are channel offsets: {', '.join('0x%04X' % o for o in offs)}. Preview mixes all streams; instruments are approximate.",
                ))
                for channel_no, off in enumerate(offs):
                    end = offs[channel_no + 1] if channel_no + 1 < len(offs) else len(data)
                    chunk = data[off:end]
                    if not chunk or chunk[:2] == b"\xff\xff":
                        continue
                    items.append(AudioItem(
                        kind="soundcard-channel",
                        key=f"soundcard-channel:{archive_name}:{res.index}:{channel_no}",
                        label=f"Sound-card channel {channel_no} {archive_name}:{res.index:03d} @0x{off:04X}",
                        archive_name=archive_name,
                        resource_index=res.index,
                        resource_type=res.rtype,
                        sound_id=channel_no,
                        offset=off,
                        length=len(chunk),
                        data=chunk,
                        notes="Single channel stream extracted from the AdLib/SoundBlaster music resource. Useful for identifying melody/bass/drum voices separately.",
                    ))
            elif looks_like_soundcard_patch(data):
                items.append(AudioItem(
                    kind="soundcard-patch",
                    key=f"soundcard-patch:{archive_name}:{res.index}",
                    label=f"Sound-card patch/instrument {archive_name}:{res.index:03d}",
                    archive_name=archive_name,
                    resource_index=res.index,
                    resource_type=res.rtype,
                    sound_id=None,
                    offset=None,
                    length=len(data),
                    data=data,
                    notes="Named instrument/driver/patch resource; export raw for now, not playable as a song.",
                ))
    order = {"pc-speaker-sfx": 0, "pc-speaker-music": 1, "soundcard-music": 2, "soundcard-channel": 3, "soundcard-patch": 4}
    return sorted(items, key=lambda item: (order.get(item.kind, 9), item.archive_name, item.resource_index, item.sound_id or 0))


NOTE_BASE_MIDI = 36  # C2-ish; the original uses a PIT divisor table, this is the closest musical preview.
TICK_SECONDS = 1.0 / 140.0


def _midi_to_freq(midi: float) -> float:
    return 440.0 * (2.0 ** ((midi - 69.0) / 12.0))


def _direct_pitch_to_freq(pitch: int, octave_shift: int = 0) -> float | None:
    """Approximate the game's direct-pitch opcode 0x?E.

    The real PC-speaker routine calculates a PIT divisor from a base value and
    the operand byte.  This preview keeps the important property: larger pitch
    bytes generally sound higher and the high nibble of the opcode shifts the
    octave/timer range.
    """
    if pitch <= 0:
        return None
    midi = 28 + (pitch / 3.0) + octave_shift * 6
    return _midi_to_freq(max(24, min(108, midi)))


def _note_to_freq(note: int, octave: int, *, transpose: int = 0) -> float:
    # note is 1..12.  Sound-card playback uses a semitone-style mapping
    # (see c384: note-1 + octave*12).  PC-speaker playback uses a PIT divisor
    # table, but the musical preview intentionally keeps the same chromatic
    # mapping so WAV/MIDI exports stay recognizable.
    midi = NOTE_BASE_MIDI + octave * 12 + (note - 1) + transpose
    return _midi_to_freq(max(24, min(108, midi)))




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
    gate_ticks = 6 if music else 2
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
                    gate_ticks = max(1, arg)
            elif hi in (1, 2):
                if arg:
                    delta = (base_ticks * arg + 50) // 100
                    bend_ticks = delta if hi == 1 else -delta
                else:
                    bend_ticks = 0
            elif hi == 3:
                gate_ticks = max(1, arg)
            elif hi == 4:
                base_ticks = max(1, arg * 4)
                bend_ticks = 0
            continue
        if lo == 0x0E:
            events.append((42, max(0.015, min(0.25, gate_ticks * TICK_SECONDS))))
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


def _duration_from_game_code(code: int, base_ticks: int, bend_ticks: int = 0) -> float:
    """Decode the second byte roughly like routine C9A4.

    If bit 7 is set the low seven bits are a direct duration.  Otherwise the
    current base duration is shifted by bits 0..2; bit 3 makes it dotted.  The
    real engine also has gate/staccato state bits; for preview we keep the full
    audible duration.
    """
    if code & 0x80:
        ticks = code & 0x7F
    else:
        ticks = max(1, base_ticks + bend_ticks)
        ticks >>= (code & 0x07)
        if code & 0x08:
            ticks += max(1, ticks // 2)
    return max(0.015, min(1.50, ticks * TICK_SECONDS))


def _pc_pitch_table(data: bytes) -> list[float | None]:
    # Kept for compatibility with older exports.  Most AE music/SFX streams do
    # not carry their own pitch table; the EXE has the divisor table.
    table: list[float | None] = []
    if len(data) < 0x96 or _u16(data, 0) != 0x0096:
        return table
    for i in range(75):
        div = _u16(data, i * 2)
        if div < 16:
            table.append(None)
        else:
            freq = PIT_HZ / div
            table.append(freq if 20.0 <= freq <= 12000.0 else None)
    return table


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
    gate_ticks = 6 if music else 2
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
                    gate_ticks = max(1, arg)
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
                # Per-channel auxiliary value in music, short gate in SFX.
                gate_ticks = max(1, arg)
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
            dur = max(0.015, min(0.25, gate_ticks * TICK_SECONDS))
            events.append((_direct_pitch_to_freq(arg, hi), dur))
            continue
        dur = _duration_from_game_code(arg, base_ticks, bend_ticks)
        if lo == 0:
            events.append((None, dur))
        elif 1 <= lo <= 12:
            events.append((_note_to_freq(lo, hi, transpose=transpose), dur))
    if not events:
        events = [(440.0, 0.08), (None, 0.08), (660.0, 0.08)]
    return events


# Backward-compatible name used by the GUI/export code.
def parse_note_pairs(
    data: bytes,
    *,
    music: bool = False,
    max_events: int = 800,
    pitch_table: list[float | None] | None = None,
    initial_base_ticks: int | None = None,
) -> list[tuple[float | None, float]]:
    return parse_game_audio_stream(data, max_events=max_events, music=music, initial_base_ticks=initial_base_ticks)

def synthesize_wav(data: bytes, path: Path | str, *, music: bool = False, speed: float = DEFAULT_PREVIEW_SPEED) -> Path:
    path = Path(path)
    streams = _streams_from_resource(data)
    pitch_table = _pc_pitch_table(data)
    shared_base = _shared_initial_base_ticks(streams, music=music)
    parsed = []
    rhythm_flags: list[bool] = []
    for stream_no, s in enumerate(streams):
        is_rhythm = music and _is_probable_rhythm_stream(s, stream_no if len(streams) > 1 else None)
        rhythm_flags.append(is_rhythm)
        if is_rhythm:
            drum_events = parse_game_audio_drum_stream(s, max_events=1800, music=music, initial_base_ticks=shared_base)
            # Store drum note numbers in the freq slot with a negative sentinel.
            parsed.append([((-float(note) if note is not None else None), dur) for note, dur in drum_events])
        else:
            parsed.append(parse_note_pairs(s, music=music, max_events=1800 if music else 200, pitch_table=pitch_table, initial_base_ticks=shared_base))
    speed = max(0.10, min(8.0, float(speed)))
    parsed = [[(freq, dur / speed) for freq, dur in events] for events in parsed]
    # Render/mix streams.
    total_duration = max(sum(d for _f, d in ev) for ev in parsed)
    total_samples = max(1, int(total_duration * SAMPLE_RATE))
    mix = [0.0] * total_samples
    for track_no, events in enumerate(parsed):
        t = 0
        phase = 0.0
        amp = 0.22 / max(1, len(parsed))
        for freq, dur in events:
            n = max(1, int(dur * SAMPLE_RATE))
            if freq is not None:
                if freq < 0:
                    # Rhythm channel: short deterministic noise/tick burst, then
                    # silence for the rest of the event duration so timing stays
                    # intact but it does not become a wrong sustained melody.
                    burst = min(n, max(1, int(0.035 * SAMPLE_RATE)))
                    seed = int(-freq) * 1103515245 + track_no * 12345
                    for j in range(burst):
                        if t + j >= total_samples:
                            break
                        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
                        mix[t+j] += amp * (1.0 if (seed & 0x4000) else -1.0)
                else:
                    step = 2.0 * math.pi * freq / SAMPLE_RATE
                    for j in range(n):
                        if t + j >= total_samples:
                            break
                        # Square-ish tone is closer to PC speaker than sine.
                        mix[t+j] += amp * (1.0 if math.sin(phase) >= 0 else -1.0)
                        phase += step
            t += n
            if t >= total_samples:
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


def write_midi(data: bytes, path: Path | str, *, speed: float = DEFAULT_PREVIEW_SPEED) -> Path:
    path = Path(path)
    streams = _streams_from_resource(data)
    ticks_per_quarter = 96

    tracks: list[bytes] = []
    tempo_track = bytearray()
    tempo_track += b"\x00\xFF\x51\x03\x07\xA1\x20"  # 120 bpm
    tempo_track += b"\x00\xFF\x2F\x00"
    tracks.append(bytes(tempo_track))

    shared_base = _shared_initial_base_ticks(streams, music=True)
    for stream_no, stream in enumerate(streams[:8]):
        is_rhythm = _is_probable_rhythm_stream(stream, stream_no if len(streams) > 1 else None)
        speed = max(0.10, min(8.0, float(speed)))
        channel = 9 if is_rhythm else (stream_no % 15)
        tr = bytearray()
        if not is_rhythm:
            tr += b"\x00" + bytes([0xC0 | channel, 80 if stream_no else 24])  # program change
        pending_delta = 0
        if is_rhythm:
            drum_events = parse_game_audio_drum_stream(stream, max_events=1800, music=True, initial_base_ticks=shared_base)
            for note, dur in [(note, dur / speed) for note, dur in drum_events]:
                ticks = max(1, int(dur * ticks_per_quarter * 2))
                if note is None:
                    pending_delta += ticks
                    continue
                audible_ticks = max(1, min(ticks, int(ticks_per_quarter * 0.10)))
                tr += _midi_varlen(pending_delta) + bytes([0x90 | channel, note, 80])
                tr += _midi_varlen(audible_ticks) + bytes([0x80 | channel, note, 0])
                pending_delta = max(0, ticks - audible_ticks)
        else:
            events = parse_game_audio_stream(stream, max_events=1800, music=True, initial_base_ticks=shared_base)
            events = [(freq, dur / speed) for freq, dur in events]
            for freq, dur in events:
                ticks = max(1, int(dur * ticks_per_quarter * 2))
                if freq is None:
                    pending_delta += ticks
                    continue
                note = _pitch_to_midi(freq)
                tr += _midi_varlen(pending_delta) + bytes([0x90 | channel, note, 80])
                tr += _midi_varlen(ticks) + bytes([0x80 | channel, note, 0])
                pending_delta = 0
        tr += _midi_varlen(pending_delta) + b"\xFF\x2F\x00"
        tracks.append(bytes(tr))

    header = b"MThd" + struct.pack(">IHHH", 6, 1 if len(tracks) > 1 else 0, len(tracks), ticks_per_quarter)
    body = bytearray()
    for tr in tracks:
        body += b"MTrk" + struct.pack(">I", len(tr)) + tr
    path.write_bytes(header + bytes(body))
    return path

def play_audio_file(path: Path | str) -> None:
    path = Path(path)
    system = platform.system().lower()
    if system == "windows":
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        return
    for cmd in (["afplay", str(path)], ["aplay", str(path)], ["paplay", str(path)], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)]):
        if shutil.which(cmd[0]):
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    raise RuntimeError("No audio player found (tried afplay/aplay/paplay/ffplay). Export WAV instead.")


def temp_preview_wav(item: AudioItem, *, speed: float = DEFAULT_PREVIEW_SPEED) -> Path:
    temp_dir = Path(tempfile.gettempdir()) / "ae_audio_atlas"
    temp_dir.mkdir(parents=True, exist_ok=True)
    safe = f"{item.kind}_{item.archive_name}_{item.resource_index}_{item.sound_id if item.sound_id is not None else 'res'}"
    path = temp_dir / f"{safe}.wav"
    return synthesize_wav(item.data, path, music=item.kind != "pc-speaker-sfx", speed=speed)
