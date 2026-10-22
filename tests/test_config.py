from pathlib import Path

import pytest

from nitaq.agent import AgentConfig


@pytest.mark.parametrize(
    "suffix,field,default,legacy,current",
    [
        ("PRIMARY_MODEL", "primary_model", "openai/gpt-oss-120b", "old-primary", "new-primary"),
        ("FAST_MODEL", "fast_model", "llama-3.1-8b-instant", "old-fast", "new-fast"),
        ("MAX_TOOL_ITERATIONS", "max_tool_iterations", 4, 2, 7),
        ("RAG_TOP_K", "rag_top_k", 5, 3, 8),
    ],
)
@pytest.mark.parametrize("mode", ["default", "legacy", "current", "both"])
def test_configuration_names(monkeypatch, tmp_path: Path, suffix, field, default, legacy, current, mode):
    for prefix in ("NITAQ", "MIZAN"):
        monkeypatch.delenv(f"{prefix}_{suffix}", raising=False)
    if mode in {"legacy", "both"}:
        monkeypatch.setenv(f"MIZAN_{suffix}", str(legacy))
    if mode in {"current", "both"}:
        monkeypatch.setenv(f"NITAQ_{suffix}", str(current))

    config = AgentConfig.from_env(tmp_path)

    expected = current if mode in {"current", "both"} else legacy if mode == "legacy" else default
    assert getattr(config, field) == expected
