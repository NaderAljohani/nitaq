from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nitaq.rag import RAGBuilder


if __name__ == "__main__":
    print(json.dumps(RAGBuilder(ROOT).build(), ensure_ascii=False, indent=2))
