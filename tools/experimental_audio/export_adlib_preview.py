from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ae_editor.game_data.dat_archive import DatArchive
from ae_editor.audio import synthesize_soundcard_music_wav, write_opl_register_trace_csv, write_midi


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a YM3812 preview and OPL init trace for a sound-card music resource")
    parser.add_argument("dat", nargs="?", default=str(ROOT / "AE000.DAT"))
    parser.add_argument("index", nargs="?", type=int, default=54)
    parser.add_argument("--exe", default=str(ROOT / "AEPROG.EXE"))
    parser.add_argument("--out", default=str(ROOT / "exports"))
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    res = DatArchive(args.dat)[args.index]
    if not res.ok:
        raise SystemExit(res.error)
    stem = f"{Path(args.dat).stem.lower()}_{args.index:03d}"
    wav = synthesize_soundcard_music_wav(res.decoded, args.exe, out / f"{stem}_ym3812.wav")
    midi = write_midi(res.decoded, out / f"{stem}_mapped.mid", audio_kind="soundcard-music")
    trace = write_opl_register_trace_csv(res.decoded, args.exe, out / f"{stem}_opl_init_trace.csv")
    print(wav)
    print(midi)
    print(trace)


if __name__ == "__main__":
    main()
