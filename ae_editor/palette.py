from __future__ import annotations

import struct
from pathlib import Path

EGA_RGBI: list[tuple[int, int, int]] = [
    (0, 0, 0), (0, 0, 170), (0, 170, 0), (0, 170, 170),
    (170, 0, 0), (170, 0, 170), (170, 85, 0), (170, 170, 170),
    (85, 85, 85), (85, 85, 255), (85, 255, 85), (85, 255, 255),
    (255, 85, 85), (255, 85, 255), (255, 255, 85), (255, 255, 255),
]


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
