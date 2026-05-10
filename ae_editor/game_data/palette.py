from __future__ import annotations

import struct
from pathlib import Path

EGA_RGBI: list[tuple[int, int, int]] = [
    (0, 0, 0), (0, 0, 170), (0, 170, 0), (0, 170, 170),
    (170, 0, 0), (170, 0, 170), (170, 85, 0), (170, 170, 170),
    (85, 85, 85), (85, 85, 255), (85, 255, 85), (85, 255, 255),
    (255, 85, 85), (255, 85, 255), (255, 255, 85), (255, 255, 255),
]


def ega_palette_register_colour(value: int) -> tuple[int, int, int]:
    """Convert an EGA palette-register value to the editor's RGB colour.

    The game programs EGA with BIOS INT 10h AH=10h/AL=00h. The value is a
    6-bit EGA colour selector: low bits are the normal B/G/R lines and high
    bits are the secondary B/G/R lines. For the editor view we collapse those
    two lines per channel into the final 16-colour digital output used by the
    game's art: a channel is on when either of its two EGA selector bits is on.

    This matters for the game's palette init: AEPROG maps palette register 15
    to selector 0x16. Treating 0x16 as a linear 64-colour DAC gives a
    yellow-green colour, but the in-game EGA art uses it as plain bright
    yellow. The rule below derives that without a special case for register 15.
    """
    value &= 0x3F

    def channel(primary_bit: int, secondary_bit: int) -> int:
        return 255 if value & (primary_bit | secondary_bit) else 0

    return (
        channel(0x04, 0x20),
        channel(0x02, 0x10),
        channel(0x01, 0x08),
    )


def ega_64_colour(value: int) -> tuple[int, int, int]:
    """Backward-compatible alias for the game's EGA register conversion."""
    return ega_palette_register_colour(value)


def extract_ega_palette_registers(exe_path: Path | str) -> dict[int, int]:
    """Return EGA palette-register remaps performed by AEPROG.EXE.

    The EGA video init contains ordinary BIOS calls of this form::

        mov ax, 1000h      ; INT 10h AH=10h AL=00h
        mov bx, cc rr      ; BH = EGA 6-bit colour, BL = palette register
        int 10h

    Scanning these calls keeps the editor tied to the game executable instead
    of duplicating the remap values as unexplained constants.  In the shipped
    EXE this yields the small palette tweak that makes logical colour 1 black
    and logical colour 15 yellow rather than the default blue/white pair.
    """
    image = mz_loaded_image(exe_path)
    remaps: dict[int, int] = {}
    marker = b"\xb8\x00\x10\xbb"
    pos = 0
    while True:
        off = image.find(marker, pos)
        if off < 0:
            break
        if off + 8 <= len(image) and image[off + 6 : off + 8] == b"\xcd\x10":
            bx = struct.unpack_from("<H", image, off + 4)[0]
            register = bx & 0xFF
            colour = (bx >> 8) & 0x3F
            if 0 <= register < 16:
                remaps[register] = colour
        pos = off + 1
    return remaps


def build_game_ega_palette(exe_path: Path | str | None = None) -> list[tuple[int, int, int]]:
    """Return the EGA palette after the game's video init remaps.

    Type-0x47 EGA pixels resolve to the low nibble of the per-image EGA lookup
    table.  That nibble selects one of the active EGA palette registers.  The
    game changes a few of those registers during video init, so the editor
    derives the final RGB colours from AEPROG.EXE when it is available.
    """
    palette = list(EGA_RGBI)
    if exe_path is None:
        return palette
    try:
        remaps = extract_ega_palette_registers(exe_path)
    except (OSError, ValueError, struct.error):
        return palette
    for register, colour in remaps.items():
        palette[register] = ega_palette_register_colour(colour)
    return palette


GAME_EGA_RGB: list[tuple[int, int, int]] = build_game_ega_palette(None)


# Standard 320x200 CGA palette 1, high intensity.
# The per-image 0x47 records contain the actual logical-colour -> CGA colour
# mapping in the high nibble of their first 16-byte table.  CGA hardware then
# displays those 2-bit colour numbers through this fixed palette.
CGA_PALETTE_1_HIGH: list[tuple[int, int, int]] = [
    (0, 0, 0),
    (85, 255, 255),
    (255, 85, 255),
    (255, 255, 255),
]


def cga_colour_from_table_byte(value: int) -> int:
    """Decode the CGA colour encoded in a 0x47 record colour-table byte.

    In the first 16-byte colour table the low nibble is the EGA logical colour.
    The high nibble is not an EGA colour; it is half of the CGA byte pattern:

        0x0 -> 0000 -> colour 0
        0x5 -> 0101 -> colour 1
        0xA -> 1010 -> colour 2
        0xF -> 1111 -> colour 3

    Duplicating that nibble gives the CGA byte for four identical 2-bit pixels
    (00/01/10/11 repeated).  The colour number is therefore the low two bits
    of that repeated pattern.
    """
    nibble = (value >> 4) & 0x0F
    repeated = (nibble << 4) | nibble
    return repeated & 0x03

def mz_loaded_image(exe_path: Path | str) -> bytes:
    """Return the in-memory image of the DOS MZ executable after its header."""
    blob = Path(exe_path).read_bytes()
    if len(blob) < 64 or blob[:2] != b"MZ":
        raise ValueError(f"{exe_path} is not an MZ executable")
    header_paragraphs = struct.unpack_from("<H", blob, 8)[0]
    return blob[header_paragraphs * 16 :]


def find_vga_palette_dac6(exe_path: Path | str) -> tuple[int, bytes]:
    """Find the custom 256-colour VGA DAC palette embedded in AEPROG.EXE.

    Reverse-engineering note: the video setup path for VGA mode calls INT 10h
    AX=1012h, BX=0, CX=256 with ES:DX pointing to DS:011e. For this binary,
    the first relocated word in the loaded image resolves DGROUP, so the loaded
    image offset is dgroup*16 + 0x011e.
    """
    image = mz_loaded_image(exe_path)
    if len(image) < 0x200:
        raise ValueError("EXE image too small")
    dgroup = struct.unpack_from("<H", image, 1)[0]
    offset = dgroup * 16 + 0x011E
    if offset + 768 > len(image):
        raise ValueError(f"VGA palette outside EXE image: {offset:#x}")
    dac = image[offset : offset + 768]
    if max(dac) >= 64:
        raise ValueError("VGA palette does not look like 6-bit DAC data")
    return offset, dac


def dac6_to_pillow_palette(dac: bytes) -> list[int]:
    """Convert 256 RGB triples in 0..63 DAC range to a Pillow 0..255 palette."""
    if len(dac) < 768:
        raise ValueError("DAC palette must contain 768 bytes")
    out: list[int] = []
    for i in range(256):
        r, g, b = dac[i * 3 : i * 3 + 3]
        out.extend([round(r * 255 / 63), round(g * 255 / 63), round(b * 255 / 63)])
    return out
