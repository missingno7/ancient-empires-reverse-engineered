# Level format notes - v33 conveyor tile cleanup

This build rolls back the v32 assumption that visible conveyor belts are control-record objects. Screenshots and `codes_hex` inspection show that belts are stored directly in the 38×18 terrain grid, similar to rope codes.

## Confirmed/supported terrain special codes

- `0x80/0x90/0xA0/0xB0/0xC0`: rope pieces rendered from `AE000:005..008`.
- `0x07`: invisible solid/support/collision marker. It is not a platform sprite.
- `0x0F`: conveyor belt family A, currently rendered as grey using `AE000:038:0,1,2`.
- `0x1F`: conveyor belt family B, currently rendered as teal using `AE000:038:12,13,14`.

`AE000:038` contains four animation frames for each family. Static previews currently use frame 0.

## Cleanup consequence

Length-prefixed control commands with args such as `0x10..0x13` are no longer drawn as visible conveyor belts. They may still be trigger/motion/state metadata, but drawing them caused duplicated and misplaced belts.

## Still unknown

The exact semantic meaning/direction of `0x0F` vs `0x1F` may be reversed if future screenshots prove it. The mapping lives in `RoomRenderer.CONVEYOR_TILE_CODES` and is intentionally centralized.
