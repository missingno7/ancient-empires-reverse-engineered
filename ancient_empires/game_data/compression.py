from __future__ import annotations

import struct


def read_offsets(data: bytes) -> list[int]:
    """Read the little-endian resource offset table used by AE*.DAT."""
    if len(data) < 8:
        raise ValueError("DAT file too small")
    first = struct.unpack_from("<I", data, 0)[0]
    if first % 4 or first < 4 or first > len(data):
        raise ValueError("bad DAT first offset")
    count = first // 4
    offsets = list(struct.unpack_from(f"<{count}I", data, 0))
    if offsets != sorted(offsets) or offsets[-1] > len(data):
        raise ValueError("bad DAT offset table")
    return offsets


def unpack_rle(src: bytes) -> bytes:
    """Decode the signed-count RLE stage used when resource flag bit 0 is set."""
    out = bytearray()
    i = 0
    while i < len(src):
        control = src[i]
        i += 1
        signed = control if control < 0x80 else control - 0x100
        if signed > 0:
            out.extend(src[i : i + signed])
            i += signed
        else:
            if i >= len(src):
                break
            out.extend([src[i]] * (-signed + 1))
            i += 1
    return bytes(out)


class BitReader:
    """MSB-first bit reader matching the loader routine recovered from AEPROG.EXE."""

    def __init__(self, data: bytes):
        self.data = data
        # The first two bytes are part of the encoded stream header/count in the
        # original routine; the actual bitstream starts at byte 2.
        self.pos = 2
        self.bit_index = 0
        self.current = 0
        self.remaining = max(0, len(data) - 1)

    def read(self, width: int) -> int:
        value = 0
        for _ in range(width):
            self.bit_index -= 1
            if self.bit_index < 0:
                if self.pos >= len(self.data):
                    raise EOFError
                self.current = self.data[self.pos]
                self.pos += 1
                self.bit_index = 7
                self.remaining -= 1
                if self.remaining == 0:
                    raise EOFError
            bit = (self.current >> 7) & 1
            self.current = (self.current << 1) & 0xFF
            value = ((value << 1) | bit) & 0xFFFF
        return value


def unpack_lzw(src: bytes) -> bytes:
    """Decode the game's LZW-like stage used when resource flag bit 1 is set.

    Code 0x100 increases the code width. Codes 0x101+ reference slices already
    emitted to the output buffer. This intentionally mirrors the known-good VGA
    asset decoder rather than a generic LZW implementation.
    """
    if len(src) <= 2:
        return b""
    reader = BitReader(src)
    out = bytearray()
    offsets: list[int] = []
    width = 9

    def emit(code: int) -> None:
        if code <= 0xFF:
            out.append(code)
            return
        idx = code - 0x101
        if idx < 0 or idx + 1 >= len(offsets):
            raise ValueError(f"bad LZW reference {code:#x}")
        start, end = offsets[idx], offsets[idx + 1]
        out.extend(out[start:end])

    while True:
        offsets.append(len(out))
        while True:
            try:
                code = reader.read(width)
            except EOFError:
                return bytes(out)
            if code == 0x100:
                width += 1
                if width > 16:
                    return bytes(out)
                continue
            break
        emit(code)
        while True:
            try:
                code = reader.read(width)
            except EOFError:
                return bytes(out)
            if code == 0x100:
                width += 1
                if width > 16:
                    return bytes(out)
                continue
            break
        emit(code)


def decode_resource_block(block: bytes) -> tuple[int, int, bytes]:
    """Return (resource_type, compression_flags, decoded_payload)."""
    if len(block) < 2:
        raise ValueError("empty DAT resource block")
    rtype, flags = block[0], block[1]
    data = block[2:]
    if flags & 0x02:
        data = unpack_lzw(data)
    if flags & 0x01:
        data = unpack_rle(data)
    return rtype, flags, data
