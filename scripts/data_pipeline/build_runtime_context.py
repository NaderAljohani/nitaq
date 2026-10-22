from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mizan.tools.modon import load_modon_regional_context


RUNTIME_DIR = ROOT / "data" / "processed" / "runtime"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    copies = {
        ROOT / "data" / "raw" / "context" / "imf_portwatch_monthly_long_2019_2026.csv": (
            RUNTIME_DIR / "portwatch_monthly_activity_2019_2026.csv"
        ),
        ROOT / "data" / "raw" / "context" / "logisti_logistics_centers_snapshot_2026-07-28.csv": (
            RUNTIME_DIR / "logistics_centers_snapshot_2026-07-28.csv"
        ),
    }
    for source, destination in copies.items():
        if not source.exists():
            raise FileNotFoundError(source)
        shutil.copy2(source, destination)

    modon = load_modon_regional_context(ROOT)
    modon_path = RUNTIME_DIR / "modon_regional_context_2023_2024.csv"
    modon["table"].to_csv(modon_path, index=False, encoding="utf-8")

    outputs = [*copies.values(), modon_path]
    manifest = {
        "built_on": date.today().isoformat(),
        "purpose": "Small validated runtime datasets; full raw sources are kept in the local ZIP archive.",
        "outputs": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in outputs
        ],
        "modon_unmapped_industrial_cities": modon.get("unmapped_industrial_cities", []),
        "raw_archive": "MIZAN_CLIENT_PACKAGE/01_CORE_SOURCE_DATA/RAW_DATA_ARCHIVE/raw_sources_2026-07-30.zip",
    }
    (RUNTIME_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"runtime_files": len(outputs), "runtime_dir": str(RUNTIME_DIR)}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
