from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
from typing import Iterator

from .compression import decode_resource_block, read_offsets
from .type47 import iter_type47


@dataclass(frozen=True)
class Resource:
    index: int
    rtype: int
    flags: int
    decoded: bytes
    raw: bytes
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


class DatArchive:
    """Reader for AE000.DAT / AE001.DAT resource archives.

    The archive starts with a little-endian 32-bit offset table. Each resource
    starts with two bytes: resource type and compression flags. Compression is
    the same as in the supplied v9 image decoder: bit 1 = LZW-like stream,
    bit 0 = RLE stream.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.blob = self.path.read_bytes()
        self.offsets = read_offsets(self.blob)
        self.resources = self._read_resources()

    def _read_resources(self) -> list[Resource]:
        resources: list[Resource] = []
        for index in range(len(self.offsets) - 1):
            raw = self.blob[self.offsets[index]:self.offsets[index + 1]]
            try:
                rtype, flags, decoded = decode_resource_block(raw)
                resources.append(Resource(index, rtype, flags, decoded, raw))
            except ValueError as exc:  # keep archive browsable even if one entry fails
                resources.append(Resource(index, -1, -1, b"", raw, repr(exc)))
        return resources

    def __len__(self) -> int:
        return len(self.resources)

    def __getitem__(self, index: int) -> Resource:
        return self.resources[index]

    def iter_images(self) -> Iterator[tuple[Resource, str, bytes]]:
        """Yield all type47 image payloads as (resource, subname, payload)."""
        for res in self.resources:
            if not res.ok:
                continue
            for bitmap in iter_type47(res.decoded, res.rtype):
                yield res, bitmap.subname, bitmap.payload

    def build_blob_with_decoded_replacements(self, replacements: dict[int, bytes]) -> bytes:
        """Return a DAT blob with selected resources replaced by plain payloads.

        MVP editing writes changed level resources uncompressed (`flags=0`) and
        preserves every untouched resource byte-for-byte.  The existing reader
        and game resource format both model `flags=0` as plain decoded payload.
        """
        blocks: list[bytes] = []
        for resource in self.resources:
            replacement = replacements.get(resource.index)
            if replacement is None:
                blocks.append(resource.raw)
            else:
                blocks.append(bytes([resource.rtype, 0]) + replacement)

        first_offset = (len(blocks) + 1) * 4
        offsets: list[int] = []
        cursor = first_offset
        for block in blocks:
            offsets.append(cursor)
            cursor += len(block)
        offsets.append(cursor)
        table = struct.pack(f"<{len(offsets)}I", *offsets)
        return table + b"".join(blocks)
