from pathlib import Path

import pytest

from mizan.agent import AgentConfig


@pytest.mark.parametrize(
    "suffix,field,default,current",
    [
        ("PRIMARY_MODEL", "primary_model", "openai/gpt-oss-120b", "configured-primary"),
        ("FAST_MODEL", "fast_model", "llama-3.1-8b-instant", "configured-fast"),
        ("MAX_TOOL_ITERATIONS", "max_tool_iterations", 4, 7),
        ("RAG_TOP_K", "rag_top_k", 5, 8),
    ],
)
@pytest.mark.parametrize("configured", [False, True])
def test_configuration_names(monkeypatch, tmp_path: Path, suffix, field, default, current, configured):
    monkeypatch.delenv(f"MIZAN_{suffix}", raising=False)
    if configured:
        monkeypatch.setenv(f"MIZAN_{suffix}", str(current))

    config = AgentConfig.from_env(tmp_path)

    expected = current if configured else default
    assert getattr(config, field) == expected
