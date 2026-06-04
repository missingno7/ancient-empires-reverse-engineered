from __future__ import annotations

from dataclasses import dataclass

from ..constants import (
    LEVEL_PART_ACTOR_BLOCK_OFFSET,
    LEVEL_PART_ACTOR_BLOCK_SIZE,
    ROOM_COLUMNS,
    ROOM_COUNT,
    ROOM_ROWS,
    ROOM_SCREEN_WIDTH_PX,
)
from .actor_dsl import opcode_size, s8
from .level_format import Level, LevelPart, Room
from .room_payload import (
    ACTOR_RECORD_SIZE,
    parse_conveyor_visual_records,
    parse_exe_payload_directory,
    parse_platform_triplets,
    part_apple_marker,
    record12_green_block_records,
    room_cell_for_runtime_offset,
    runtime_offset_for_room_cell,
    set_part_apple_marker,
)

SCREEN_HALF_RAW = ROOM_SCREEN_WIDTH_PX // 2
REFLECTOR_FRAME_COUNT = 24

CONVEYOR_TILE_SWAP = {0x0F: 0x1F, 0x1F: 0x0F}
HORIZONTAL_PLATFORM_FLAG_SWAP = {0x40: 0x60, 0x60: 0x40}
PLAYER_X_CONDITION_SWAP = {0x17: 0x18, 0x18: 0x17}
CONVEYOR_CONDITION_SWAP = {0x15: 0x16, 0x16: 0x15}


def _sprite_size(graphics, archive: str, resource_id: int, sprite_index: int = 0, default: tuple[int, int] = (24, 24)) -> tuple[int, int]:
    """Return sprite size when GraphicsSet is available, otherwise a stable default."""
    if graphics is None:
        return default
    try:
        sprite = graphics.sprite(archive, resource_id, sprite_index)
    except Exception:
        sprite = None
    if sprite is None:
        return default
    return sprite.width, sprite.height


@dataclass(frozen=True)
class FlipReport:
    rooms: int = 0
    actors: int = 0
    script_instructions: int = 0
    controls: int = 0
    compact_entries: int = 0
    conveyors: int = 0
    platforms: int = 0
    green_blocks: int = 0

    def __add__(self, other: "FlipReport") -> "FlipReport":
        return FlipReport(
            rooms=self.rooms + other.rooms,
            actors=self.actors + other.actors,
            script_instructions=self.script_instructions + other.script_instructions,
            controls=self.controls + other.controls,
            compact_entries=self.compact_entries + other.compact_entries,
            conveyors=self.conveyors + other.conveyors,
            platforms=self.platforms + other.platforms,
            green_blocks=self.green_blocks + other.green_blocks,
        )

    def summary(self) -> str:
        return (
            f"flipped {self.rooms} rooms, {self.actors} actors, "
            f"{self.script_instructions} script instructions, {self.controls} controls, "
            f"{self.compact_entries} compact objects, {self.conveyors} conveyors, "
            f"{self.platforms} platforms, {self.green_blocks} green blocks"
        )


def _s8_byte(value: int) -> int:
    value &= 0xFF
    return value - 0x100 if value & 0x80 else value


def _s16_word(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def mirror_x_raw(x_raw: int) -> int:
    """Mirror a zero-width half-pixel x anchor.

    This is appropriate only for point-like anchors. Wide objects should use
    ``mirror_x_raw_footprint`` so the mirrored left edge lands where the old
    right edge was.
    """
    return mirror_x_raw_footprint(x_raw, origin_px=0, width_px=0)


def mirror_x_raw_footprint(x_raw: int, *, origin_px: int, width_px: int) -> int:
    """Mirror a half-pixel x coordinate while preserving object footprint.

    Many room payload records store an object anchor, not the sprite top-left.
    If the renderer computes ``left = x_raw*2 - origin_px``, then a true
    horizontal mirror must satisfy ``new_left = room_width - left - width``.
    Solving that in the stored half-pixel coordinate gives the expression below.

    ``origin_px == width_px/2`` naturally degenerates to a point-anchor mirror,
    which keeps centered objects stable while still handling wide, left/right
    anchored objects correctly.
    """
    return (SCREEN_HALF_RAW - _s8_byte(x_raw) + int(origin_px) - int(width_px) // 2) & 0xFF


def mirror_actor_x_footprint(x: int, *, origin_px: int, width_px: int) -> int:
    """Mirror an actor pixel-space x anchor while preserving sprite footprint."""
    return (ROOM_SCREEN_WIDTH_PX - _s16_word(x) + int(origin_px) - int(width_px)) & 0xFFFF


def mirror_actor_x(x: int) -> int:
    """Mirror an actor/player x coordinate stored directly in pixels.

    Actor coordinates are signed-ish runtime positions; enemies can be just
    outside the viewport. Preserve that by returning a wrapped 16-bit value.
    """
    return (ROOM_SCREEN_WIDTH_PX - _s16_word(x)) & 0xFFFF


def mirror_tile_x(x: int) -> int:
    return ROOM_COLUMNS - 1 - x


def mirror_runtime_offset(offset: int) -> int:
    cell = room_cell_for_runtime_offset(offset)
    if cell is None:
        return offset
    room_index, x, y = cell
    mirrored_x = mirror_tile_x(x)
    # Some script offsets can point to the hidden two-cell runtime buffer just
    # before the visible room. Keep those untouched rather than inventing a
    # lossy mapping.
    try:
        return runtime_offset_for_room_cell(room_index, mirrored_x, y)
    except ValueError:
        return offset




def _actor_sprite_resource(frame: int) -> tuple[int, int, int] | None:
    """Return (frame_start, frame_count, resource_id) for known actor frames."""
    for frame_start, count, resource_id in (
        (0x00, 8, 20),
        (0x08, 7, 20),
        (0x0F, 8, 20),
        (0x17, 4, 21),
        (0x1B, 5, 21),
        (0x20, 11, 22),
        (0x2B, 2, 22),
        (0x2D, 5, 22),
        (0x32, 5, 22),
        (0x37, 4, 22),
        (0x3B, 4, 22),
        (0x3F, 3, 22),
        (0x42, 8, 22),
        (0x4A, 6, 22),
        (0x50, 1, 22),
    ):
        if frame_start <= frame < frame_start + count:
            return frame_start, count, resource_id
    return None


# Actors share the uniform sprite anchor X=8 recovered from the AEPROG actor
# draw loop at 0x4ef8 (see coordinates.actor_xy).  The horizontal mirror must
# use the same anchor the renderer uses so a flipped actor lands pixel-correct.
_ACTOR_ANCHOR_X = 8


def _toggle_packed_frame_variant(value: int) -> int:
    # Actor packed frame bytes use bit 7 as the left/right sprite variant in the
    # renderer/simulation. A horizontal mirror should flip that facing bit while
    # preserving the frame delta/frame id in the low seven bits.
    return (value ^ 0x80) & 0xFF


def _mirror_reflector_code(code: int) -> int:
    flags = code & 0xC0
    frame = code & 0x3F
    if frame < REFLECTOR_FRAME_COUNT:
        frame = (-frame) % REFLECTOR_FRAME_COUNT
    # Mirroring reverses clockwise/counter-clockwise rotation semantics.
    flags ^= 0x40
    return (flags | frame) & 0xFF


def _mirror_visual_code(code: int) -> int:
    # Main visual-table codes use bit 0x40 as a horizontal mirror flag for many
    # decals. Toggling it gives a reversible mirrored visual without changing
    # the low six-bit sprite id.
    return (code ^ 0x40) & 0xFF


def _mirror_platform_flags(flags: int) -> int:
    high = flags & 0xF0
    swapped = HORIZONTAL_PLATFORM_FLAG_SWAP.get(high, high)
    return (flags & 0x0F) | swapped


def _mirror_room_tiles(room: Room) -> None:
    new_tiles: list[int] = []
    for y in range(ROOM_ROWS):
        row = [room.get(x, y) for x in range(ROOM_COLUMNS)]
        row = [CONVEYOR_TILE_SWAP.get(value, value) for value in reversed(row)]
        new_tiles.extend(row)
    room.tiles = new_tiles


def _mirror_platform_triplets(room: Room, graphics=None) -> int:
    count = 0
    data = bytearray(room.trailing)
    for triplet in parse_platform_triplets(room):
        off = triplet.source_offset
        data[off] = _mirror_platform_flags(data[off])
        # Preserve the visible platform footprint. The payload x is the same
        # anchor used by engine.platform_xy: left = x_raw*2 - 12.
        if triplet.orientation == "horizontal":
            width, _height = _sprite_size(graphics, "AE000", 47, 0, default=(56, 16))
        elif triplet.orientation == "vertical":
            width, _height = _sprite_size(graphics, "AE000", 48, 0, default=(16, 56))
        else:
            width = 16
        data[off + 1] = mirror_x_raw_footprint(data[off + 1], origin_px=12, width_px=width)
        count += 1
    room.trailing = bytes(data)
    return count


def _mirror_conveyor_visuals(room: Room) -> int:
    count = 0
    data = bytearray(room.trailing)
    for cv in parse_conveyor_visual_records(room):
        length = cv.length
        mirrored_start = max(0, min(ROOM_COLUMNS - 1, ROOM_COLUMNS - (cv.start_x + length)))
        data[cv.source_offset] = max(0, min(0xFF, mirrored_start * 4 + 2))
        count += 1
    room.trailing = bytes(data)
    return count


def _mirror_control_records(room: Room, graphics=None) -> int:
    directory = parse_exe_payload_directory(room)
    if directory is None:
        return 0
    data = bytearray(room.trailing)
    count = 0
    for record in directory.control_records:
        # body layout: command, x_raw, y, optional args/targets...
        if len(record.body) >= 3:
            # Most control sprites are drawn as left = x_raw*2 - 12 and are
            # roughly 24 px wide, so this stays equivalent to a centered mirror
            # while documenting the anchor/width rule for future calibrated
            # control families.
            data[record.source_offset + 2] = mirror_x_raw_footprint(record.body[1], origin_px=12, width_px=24)
            count += 1
    room.trailing = bytes(data)
    return count


def _mirror_compact3_sections(room: Room, part_theme: int = 0, graphics=None) -> int:
    directory = parse_exe_payload_directory(room)
    if directory is None or directory.sections is None:
        return 0
    data = bytearray(room.trailing)
    count = 0
    for table_name, table in (
        ("section_a", directory.sections.section_a),
        ("section_c", directory.sections.section_c),
        ("visual", directory.sections.visual),
    ):
        if table is None:
            continue
        for entry in table.entries:
            off = entry.source_offset
            if table_name == "section_a":
                # Symbol markers are drawn centered on AE000:009.
                width, _height = _sprite_size(graphics, "AE000", 9, 0, default=(24, 24))
                data[off] = mirror_x_raw_footprint(data[off], origin_px=width // 2, width_px=width)
            elif table_name == "section_c":
                # Reflectors/crystals are compact3 sprites with the normal
                # screen_exe anchor.  Mirror the footprint, then mirror the
                # orientation/rotation encoded in the code byte.
                sprite_index = data[off + 2] & 0x3F
                width, _height = _sprite_size(graphics, "AE000", 19, sprite_index, default=(24, 24))
                data[off] = mirror_x_raw_footprint(data[off], origin_px=12, width_px=width)
                data[off + 2] = _mirror_reflector_code(data[off + 2])
            elif table_name == "visual":
                # Theme decor also uses the compact3 screen_exe anchor.  Use
                # actual decoded sprite width when available; otherwise the
                # old centered transform is preserved by the 24 px fallback.
                code = data[off + 2]
                if code in {0x8E, 0xCE}:
                    width, _height = _sprite_size(graphics, "AE000", 44, 0, default=(16, 16))
                elif code in {0x7D, 0x3D}:
                    width, _height = _sprite_size(graphics, "AE000", 19, 2, default=(24, 24))
                else:
                    width, _height = _sprite_size(graphics, "AE001", 25 + part_theme, code & 0x3F, default=(24, 24))
                data[off] = mirror_x_raw_footprint(data[off], origin_px=12, width_px=width)
                data[off + 2] = _mirror_visual_code(data[off + 2])
            else:
                data[off] = mirror_x_raw(data[off])
            count += 1

    animated = directory.sections.animated_decor
    if animated is not None:
        for record in animated.records:
            off = record.source_offset
            sprite_index = record.preview_sprite_index
            width, _height = _sprite_size(graphics, "AE001", 25 + part_theme, sprite_index, default=(24, 24))
            data[off + 1] = mirror_x_raw_footprint(data[off + 1], origin_px=12, width_px=width)
            count += 1
    room.trailing = bytes(data)
    return count


def _mirror_green_block_raw_x(raw_x: int) -> int:
    # Green-block raw x maps to top-left pixel x = raw_x*2 - 8 and occupies
    # six terrain cells (48 px). Mirror the full footprint, not just its anchor.
    return (SCREEN_HALF_RAW - 16 - _s8_byte(raw_x)) & 0xFF


def _mirror_green_blocks(room: Room) -> int:
    offset, records = record12_green_block_records(room)
    if offset is None:
        return 0
    data = bytearray(room.trailing)
    for index, rec in enumerate(records):
        if len(rec) < 4:
            continue
        off = offset + 1 + index * 12
        data[off] = _mirror_green_block_raw_x(rec[0])
        data[off + 2] = _mirror_green_block_raw_x(rec[2])
    room.trailing = bytes(data)
    return len(records)


def _mirror_tail_marker(part: LevelPart, room_index: int, graphics=None) -> None:
    marker = part_apple_marker(part, room_index)
    if marker is not None:
        # Red apples are stored/rendered as a 16px top-left pickup marker:
        # left = x_raw*2 - 6.  Do not use decoded sprite width here; transparent
        # bitmap margins would move the gameplay marker away from its mirror.
        set_part_apple_marker(
            part,
            room_index,
            x_raw=mirror_x_raw_footprint(marker.x_raw, origin_px=6, width_px=16),
            y=marker.y_raw,
        )


def _mirror_room(room: Room, *, part_theme: int = 0, graphics=None) -> FlipReport:
    _mirror_room_tiles(room)
    platforms = _mirror_platform_triplets(room, graphics=graphics)
    conveyors = _mirror_conveyor_visuals(room)
    controls = _mirror_control_records(room, graphics=graphics)
    compact = _mirror_compact3_sections(room, part_theme=part_theme, graphics=graphics)
    green = _mirror_green_blocks(room)
    return FlipReport(
        rooms=1,
        controls=controls,
        compact_entries=compact,
        conveyors=conveyors,
        platforms=platforms,
        green_blocks=green,
    )


def _mirror_header(part: LevelPart, graphics=None) -> None:
    header = bytearray(part.header)
    if len(header) >= 5:
        # The stored player start is the runtime/gameplay x anchor. Mirror that
        # anchor, not the decorative preview sprite drawn around it.
        header[3] = mirror_x_raw(header[3])  # player start
    if len(header) >= 8 and header[5] < ROOM_COUNT:
        width, _height = _sprite_size(graphics, "AE001", 21 + part.theme, 0, default=(46, 33))
        header[6] = mirror_x_raw_footprint(header[6], origin_px=12, width_px=width)  # exit door
    if len(header) >= 0x14:
        for i in range(6):
            if header[0x08 + i]:
                # Header artifacts use header_object_xy: left = x_raw*2 - 8,
                # with a calibrated 16px pickup footprint in the editor.
                header[0x0E + i] = mirror_x_raw_footprint(header[0x0E + i], origin_px=8, width_px=16)
    part.header = bytes(header)


def _mirror_room_links(part: LevelPart) -> None:
    header = bytearray(part.header)
    if len(header) < 0x2E:
        return
    left_start, right_start = 0x1A, 0x24
    for i in range(ROOM_COUNT):
        if right_start + i >= len(header) or left_start + i >= len(header):
            break
        header[left_start + i], header[right_start + i] = header[right_start + i], header[left_start + i]
    part.set_part_bytes(0, header)


def _read_u16(data: bytes | bytearray, offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8)


def _write_u16(data: bytearray, offset: int, value: int) -> None:
    data[offset] = value & 0xFF
    data[offset + 1] = (value >> 8) & 0xFF


def _iter_actor_script_offsets(block: bytes | bytearray) -> list[int]:
    starts: set[int] = set()
    count = min(block[0] if block else 0, (LEVEL_PART_ACTOR_BLOCK_SIZE - 1) // ACTOR_RECORD_SIZE)
    record_end = 1 + count * ACTOR_RECORD_SIZE
    for index in range(count):
        rec = 1 + index * ACTOR_RECORD_SIZE
        for field in (0x0D, 0x0F, 0x17):
            value = _read_u16(block, rec + field)
            if record_end <= value < LEVEL_PART_ACTOR_BLOCK_SIZE:
                starts.add(value)
    return sorted(starts)


def _is_padding_end(block: bytes | bytearray, pc: int) -> bool:
    return block[pc] == 0x00 and not any(block[pc + 1:pc + 8])


def _rewrite_script_instruction(block: bytearray, pc: int) -> bool:
    op = block[pc]
    try:
        size = opcode_size(op)
    except Exception:
        return False
    if pc + size > len(block):
        return False

    if op == 0x0E and size >= 4:
        block[pc + 1] = (-s8(block[pc + 1])) & 0xFF
        block[pc + 3] = _toggle_packed_frame_variant(block[pc + 3])
        return True
    if op == 0x0F and size >= 4:
        block[pc + 1] = mirror_x_raw(block[pc + 1])
        block[pc + 3] = _toggle_packed_frame_variant(block[pc + 3])
        return True
    if op == 0x10 and size >= 5:
        block[pc + 1] = mirror_x_raw(block[pc + 1])
        block[pc + 3] = _toggle_packed_frame_variant(block[pc + 3])
        return True
    if op == 0x0D and size >= 2:
        block[pc + 1] = _toggle_packed_frame_variant(block[pc + 1])
        return True
    if op in CONVEYOR_CONDITION_SWAP and size >= 3:
        block[pc] = CONVEYOR_CONDITION_SWAP[op]
        _write_u16(block, pc + 1, mirror_runtime_offset(_read_u16(block, pc + 1)))
        return True
    if op in {0x13, 0x14} and size >= 3:
        _write_u16(block, pc + 1, mirror_runtime_offset(_read_u16(block, pc + 1)))
        return True
    if op in PLAYER_X_CONDITION_SWAP and size >= 2:
        block[pc] = PLAYER_X_CONDITION_SWAP[op]
        block[pc + 1] = mirror_x_raw(block[pc + 1])
        return True
    return False


def _mirror_actor_scripts(block: bytearray) -> int:
    count = 0
    seen: set[int] = set()
    stack = list(_iter_actor_script_offsets(block))
    while stack:
        pc = stack.pop()
        while 0 <= pc < len(block) and pc not in seen:
            seen.add(pc)
            op = block[pc]
            try:
                size = opcode_size(op)
            except Exception:
                break
            if pc + size > len(block):
                break
            if _rewrite_script_instruction(block, pc):
                count += 1
            # Follow relative branch targets enough to rewrite shared routines;
            # preserve branch bytes themselves so control flow is unchanged.
            if op in {0x01, 0x02, 0x04, 0x05, 0x06} and size >= 3:
                rel = _read_u16(block, pc + 1)
                if rel & 0x8000:
                    rel -= 0x10000
                stack.append(pc + size + rel)
            if _is_padding_end(block, pc) or op == 0x03:
                break
            pc += size
    return count


def _mirror_actors(part: LevelPart, graphics=None) -> tuple[int, int]:
    raw = bytearray(part.raw)
    start = LEVEL_PART_ACTOR_BLOCK_OFFSET
    end = start + LEVEL_PART_ACTOR_BLOCK_SIZE
    if len(raw) < end:
        return 0, 0
    block = bytearray(raw[start:end])
    actor_count = min(block[0] if block else 0, (LEVEL_PART_ACTOR_BLOCK_SIZE - 1) // ACTOR_RECORD_SIZE)
    for index in range(actor_count):
        rec = 1 + index * ACTOR_RECORD_SIZE
        x = _read_u16(block, rec + 0x02)
        frame = block[rec + 0x06] & 0x7F
        mapping = _actor_sprite_resource(frame)
        if mapping is not None:
            frame_min, _count, resource_id = mapping
            width, _height = _sprite_size(graphics, "AE000", resource_id, frame - frame_min, default=(24, 24))
        else:
            width = 24
        _write_u16(block, rec + 0x02, mirror_actor_x_footprint(x, origin_px=_ACTOR_ANCHOR_X, width_px=width))
        block[rec + 0x07] = _toggle_packed_frame_variant(block[rec + 0x07])
    script_count = _mirror_actor_scripts(block)
    part.set_part_bytes(LEVEL_PART_ACTOR_BLOCK_OFFSET, block)
    return actor_count, script_count


def flip_level_horizontally(level: Level, graphics=None) -> FlipReport:
    """Mirror one full level horizontally, including both difficulty parts."""
    report = FlipReport()
    for part in level.parts:
        _mirror_header(part, graphics=graphics)
        _mirror_room_links(part)
        for room in part.rooms:
            report += _mirror_room(room, part_theme=part.theme, graphics=graphics)
            _mirror_tail_marker(part, room.index, graphics=graphics)
        actors, scripts = _mirror_actors(part, graphics=graphics)
        report += FlipReport(actors=actors, script_instructions=scripts)
    return report


def assert_double_flip_is_identity(level_factory) -> None:
    """Test helper: level_factory must return a fresh Level instance."""
    level = level_factory()
    original = level.to_bytes()
    flip_level_horizontally(level)
    flip_level_horizontally(level)
    after = level.to_bytes()
    if after != original:
        for index, (a, b) in enumerate(zip(original, after)):
            if a != b:
                raise AssertionError(f"double horizontal flip changed byte {index:#x}: {a:02X} -> {b:02X}")
        raise AssertionError("double horizontal flip changed level size")
