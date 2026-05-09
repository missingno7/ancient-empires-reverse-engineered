# Audio: recovered AdLib / OPL instrument table

The AdLib/Sound Blaster music path does not use `AE000:061/062` as instruments. Those resources are high-score/player tables.

The real FM instrument table is embedded in `AEPROG.EXE` at `DS:301A`. The loader at `D8F0` multiplies the per-song instrument id by `0x38` and passes that 56-byte record into `DA66/E0C0`, which copies two 13-word operator definitions and two waveform values into the runtime OPL voice state.

Relevant ASM flow:

```text
D8F0: instrument_id * 0x38 + DS:301A -> instrument record
DA66: record + 0x00 -> operator A, record + 0x1A -> operator B
E1F2/E372/E2D6/E324/E44B: emit OPL 40/20/60/80/E0 registers
E27B: emit OPL C0 feedback/connection
C898: write OPL register/value via base port DS:1830
```

## AE000:054 instruments

`AE000:054` header selects these OPL ids:

```text
01 1B 0F 0E 12 0F 0E 17 14
```

Decoded patch summaries used by that music:

- `01`: `OPL patch 01: C0=06; mod: 20=31 40=43 60=6E 80=17 E0=01 mul=1 TL=03 ADSR=6/1/E/7 flags=SK; car: 20=22 40=05 60=8B 80=0C E0=02 mul=2 TL=05 ADSR=8/0/B/C flags=S`
- `1B`: `OPL patch 1B: C0=00; mod: 20=31 40=1C 60=41 80=0B E0=00 mul=1 TL=1C ADSR=4/0/1/B flags=SK; car: 20=61 40=80 60=92 80=3B E0=00 mul=1 TL=00 ADSR=9/3/2/B flags=VS`
- `0F`: `OPL patch 0F: C0=0E; mod: 20=01 40=4F 60=71 80=53 E0=00 mul=1 TL=0F ADSR=7/5/1/3 flags=-; car: 20=12 40=00 60=52 80=7C E0=00 mul=2 TL=00 ADSR=5/7/2/C flags=K`
- `0E`: `OPL patch 0E: C0=0C; mod: 20=01 40=4F 60=F1 80=53 E0=00 mul=1 TL=0F ADSR=F/5/1/3 flags=-; car: 20=11 40=00 60=D2 80=74 E0=00 mul=1 TL=00 ADSR=D/7/2/4 flags=K`
- `12`: `OPL patch 12: C0=02; mod: 20=01 40=46 60=F1 80=83 E0=00 mul=1 TL=06 ADSR=F/8/1/3 flags=-; car: 20=61 40=03 60=31 80=86 E0=00 mul=1 TL=03 ADSR=3/8/1/6 flags=VS`
- `17`: `OPL patch 17: C0=0F; mod: 20=04 40=00 60=F7 80=B5 E0=00 mul=4 TL=00 ADSR=F/B/7/5 flags=-; car: 20=00 40=00 60=D6 80=4F E0=00 mul=0 TL=00 ADSR=D/4/6/F flags=-`
- `14`: `OPL patch 14: C0=06; mod: 20=B1 40=8B 60=71 80=11 E0=00 mul=1 TL=0B ADSR=7/1/1/1 flags=TSK; car: 20=61 40=40 60=42 80=15 E0=01 mul=1 TL=00 ADSR=4/1/2/5 flags=VS`

## Full extracted table

| id | C0 | mod 20/40/60/80/E0 | car 20/40/60/80/E0 | comment |
|---:|---:|---|---|---|
| `00` | `08` | `24 4F F2 0B 00` | `31 00 52 0B 00` |  |
| `01` | `06` | `31 43 6E 17 01` | `22 05 8B 0C 02` |  |
| `02` | `0E` | `00 0B A8 4C 00` | `00 00 D6 4F 00` |  |
| `03` | `08` | `64 DB FF 01 00` | `3E C0 F3 62 00` |  |
| `04` | `08` | `07 4F F2 60 00` | `12 00 F2 72 00` |  |
| `05` | `0C` | `64 DB FF 01 00` | `3E C0 F5 F3 00` |  |
| `06` | `06` | `32 9A 51 1B 00` | `61 82 A2 3B 00` |  |
| `07` | `01` | `21 83 74 17 00` | `A2 8D 65 17 00` |  |
| `08` | `0A` | `21 9F 53 5A 00` | `21 80 AA 1A 00` |  |
| `09` | `08` | `31 48 F1 53 00` | `32 00 F2 27 02` |  |
| `0A` | `03` | `01 11 F2 1F 00` | `01 00 F5 88 00` |  |
| `0B` | `04` | `02 29 F5 75 00` | `01 83 F2 F3 00` |  |
| `0C` | `00` | `32 44 F8 FF 00` | `11 00 F5 7F 00` |  |
| `0D` | `0E` | `B1 C5 6E 17 00` | `22 05 8B 0E 00` |  |
| `0E` | `0C` | `01 4F F1 53 00` | `11 00 D2 74 00` |  |
| `0F` | `0E` | `01 4F 71 53 00` | `12 00 52 7C 00` |  |
| `10` | `01` | `01 40 F1 53 00` | `08 40 F1 53 00` |  |
| `11` | `06` | `01 40 F1 53 00` | `08 40 F1 53 01` |  |
| `12` | `02` | `01 46 F1 83 00` | `61 03 31 86 00` |  |
| `13` | `02` | `01 47 F1 83 00` | `61 03 91 86 00` |  |
| `14` | `06` | `B1 8B 71 11 00` | `61 40 42 15 01` |  |
| `15` | `08` | `E1 4F B1 D3 03` | `21 00 12 74 01` |  |
| `16` | `02` | `06 00 F0 F0 00` | `00 00 F8 B6 00` |  |
| `17` | `0F` | `04 00 F7 B5 00` | `00 00 D6 4F 00` |  |
| `18` | `01` | `02 00 C8 97 00` | `30 00 E0 40 00` |  |
| `19` | `0E` | `26 03 E0 F0 00` | `1E 00 FF 31 00` |  |
| `1A` | `00` | `B1 1C 41 1F 00` | `61 80 92 3B 00` |  |
| `1B` | `00` | `31 1C 41 0B 00` | `61 80 92 3B 00` |  |
| `1C` | `00` | `31 1C 23 1D 00` | `61 80 52 3B 00` |  |
| `1D` | `0E` | `21 19 43 8C 00` | `21 80 85 2F 00` |  |
| `1E` | `00` | `31 1C 51 03 00` | `61 80 54 67 00` |  |
| `1F` | `0E` | `E1 88 62 29 00` | `22 80 53 2C 00` |  |
| `20` | `00` | `06 73 F6 54 00` | `81 03 F2 B3 00` |  |
| `21` | `0E` | `FF D4 06 28 03` | `FF FF F5 FF 03` |  |
| `22` | `07` | `F3 CF FF F2 00` | `AF E6 FF F6 00` |  |
| `23` | `00` | `F0 20 00 00 00` | `F0 00 00 00 00` |  |
| `24` | `08` | `F2 00 20 20 00` | `F4 04 44 44 00` |  |
| `25` | `01` | `F8 08 88 88 00` | `00 00 00 00 00` |  |
| `26` | `01` | `00 00 00 00 00` | `00 00 00 00 00` |  |
| `27` | `00` | `00 00 00 00 03` | `D0 01 00 00 03` |  |
