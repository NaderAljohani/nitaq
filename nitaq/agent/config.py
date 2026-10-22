from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class AgentConfig:
    root: Path
    primary_model: str = "openai/gpt-oss-120b"
    fast_model: str = "llama-3.1-8b-instant"
    max_tool_iterations: int = 4
    rag_top_k: int = 5
    max_user_chars: int = 4_000
    log_enabled: bool = False

    @classmethod
    def from_env(cls, root: str | Path | None = None) -> "AgentConfig":
        project_root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
        load_dotenv(project_root / ".env", override=False)
        return cls(
            root=project_root,
            primary_model=os.getenv("NITAQ_PRIMARY_MODEL", os.getenv("MIZAN_PRIMARY_MODEL", "openai/gpt-oss-120b")),
            fast_model=os.getenv("NITAQ_FAST_MODEL", os.getenv("MIZAN_FAST_MODEL", "llama-3.1-8b-instant")),
            max_tool_iterations=int(os.getenv("NITAQ_MAX_TOOL_ITERATIONS", os.getenv("MIZAN_MAX_TOOL_ITERATIONS", "4"))),
            rag_top_k=int(os.getenv("NITAQ_RAG_TOP_K", os.getenv("MIZAN_RAG_TOP_K", "5"))),
            log_enabled=os.getenv("NITAQ_TECHNICAL_LOG", "0").strip() == "1",
        )

    @property
    def groq_key_present(self) -> bool:
        return bool(os.getenv("GROQ_API_KEY"))

    @property
    def rag_dir(self) -> Path:
        return self.root / "data" / "processed" / "rag"

    @property
    def trace_path(self) -> Path:
        return self.root / "logs" / "agent_trace.jsonl"
