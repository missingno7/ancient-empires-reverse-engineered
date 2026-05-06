# File Format Summary

## DAT Archives

`AE000.DAT` and `AE001.DAT` are resource archives with a little-endian offset
table:

```text
uint32_le offsets[]
resource 0
resource 1
...
```

The first 32-bit value is the byte offset of the first resource, so the resource
count is:

```text
count = first_offset / 4
```

Each resource block starts with:

```text
byte rtype
byte flags
byte payload[]
```

Compression flags are applied in this order:

```text
flags & 0x02  -> LZW-like decompression
flags & 0x01  -> RLE decompression
```

## VGA Palette

`AEPROG.EXE` contains the custom VGA 256-colour DAC palette. The editor resolves
the loaded MZ image and extracts the palette used by the BIOS `INT 10h
AX=1012h` call. DAC values are expanded from 6-bit channels to Pillow-compatible
8-bit RGB triples.

## Type 0x47 Images

Type `0x47` image payloads store two logical 4-bit pixels per byte.

Important fields:

```text
0x00..0x0F  EGA colour table
0x10..0x1F  VGA colour table
0x20        row_bytes
0x21        height
0x22..      packed image bytes, row_bytes * height
```

For VGA rendering:

```text
logical_pixel -> payload[0x10 + logical_pixel] -> 8-bit VGA palette index
```

Logical colour `0` is treated as transparent for sprites.

## Level Resources

`AE001.DAT` resources `0..19` are level/cavern resources. A decoded level
resource has two difficulty parts:

```text
part 0 = Explorer
part 1 = Expert
```

Each part:

```text
0x40-byte header
13 room records * 1000 bytes
4-byte footer
```

Each room record:

```text
0x000..0x001  preamble / room metadata
0x002..0x2AD  38 * 18 terrain bytes
0x2AE..0x3E7  trailing room payload
```

The visible room viewport is `38 * 18` cells. Rendering uses an 8 px cell grid,
so the room bitmap is `304 * 144` px before zoom.

Current payload parsing starts at trailing offset `0x1E`, after the ten 3-byte
platform records. It decodes length-prefixed control records, puzzle marker
tables, record12 puzzle panels, laser crystal tables and the main compact3
visual table.

The part header also stores the conditional exit door in bytes `0x05..0x07`.
The room byte is zero-based; x/y are a bottom-center screen-space anchor. The
door uses sprite 0 from the current theme terrain bank (`AE001:021..024`).

MVP editor saves changed level resources as uncompressed DAT resources with
`flags=0`, while preserving untouched resource blocks exactly. Current editable
data is limited to terrain bytes and known header object slots.
