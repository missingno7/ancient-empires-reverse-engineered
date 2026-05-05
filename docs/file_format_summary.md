# File format summary

## DAT archive

`AE000.DAT` and `AE001.DAT` are resource archives.

Known layout:

```text
uint32_le offsets[]
resource 0
resource 1
...
```

The first 32-bit value is the byte offset of the first resource. Because the offset table itself is made of 4-byte values, the number of offsets is:

```text
count = first_offset / 4
```

Each resource block starts with:

```text
byte rtype
byte flags
byte compressed_or_plain_payload[]
```

Compression flags:

```text
flags & 0x02  -> LZW-like decompression first
flags & 0x01  -> RLE decompression second
```

So `flags == 3` means LZW-like, then RLE.

## VGA palette

`AEPROG.EXE` contains a custom VGA 256-colour DAC palette. The known-good decoder finds it by interpreting the loaded MZ image:

- the program loads the palette using BIOS `INT 10h AX=1012h`,
- for VGA mode selector byte `0x05`, it passes `DS:011e`,
- in this EXE the loaded-image offset resolves to `0xfb4e`.

The palette is stored as 256 RGB triples using 6-bit DAC values. The editor expands those to 8-bit Pillow palettes.

## type 0x47 images

The game image format stores two logical 4-bit pixels per byte.

Important fields in the type47 payload:

```text
0x00..0x0f  EGA colour table
0x10..0x1f  VGA colour table
0x20        row_bytes
0x21        height
0x22..      packed image bytes, row_bytes * height
```

For VGA rendering:

```text
logical_pixel -> payload[0x10 + logical_pixel] -> 8-bit VGA palette index
```

Logical colour `0` is treated as the transparent/blitter key for sprites.

## Level resources

Current best level layout for `AE001.DAT` resources `0..19`:

```text
0x40-byte header
38 room records
80-byte footer/trailing data
```

Each room record currently parses as:

```text
38 * 18 = 684 bytes of tile codes
```

This exactly matches the visible room grid described by screenshots: `38×18` cells. Rendering uses an 8px cell grid, giving a `304×144` room area. The game UI surrounds/crops/composes this in the full 320×200 screen.

Earlier hypotheses that the decoded level was a `136×64×3` grid or a `0x2AC + object slot` room record did not match screenshots reliably and are considered deprecated.
