"""Unit tests for ``writer.llm.call_llm`` request construction."""

from __future__ import annotations

import pytest

from openchronicle.config import Config, ModelConfig
from openchronicle.writer import llm as llm_mod

_SCHEMA = {
    "name": "block",
    "schema": {"type": "object", "properties": {"entries": {"type": "array"}}},
}


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    monkeypatch.delenv("OPENCHRONICLE_LLM_MOCK", raising=False)
    import litellm

    calls: list[dict] = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(litellm, "completion", fake_completion)
    return calls


def _cfg(**model_fields) -> Config:
    return Config(models={"default": ModelConfig(api_key="sk-test", **model_fields)})


def _call(cfg: Config, **kwargs) -> None:
    llm_mod.call_llm(cfg, "timeline", messages=[{"role": "user", "content": "hi"}], **kwargs)


def test_json_mode_defaults_to_json_object(captured: list[dict]) -> None:
    _call(_cfg(), json_mode=True, json_schema=_SCHEMA)
    assert captured[0]["response_format"] == {"type": "json_object"}


def test_json_schema_format_sends_caller_schema(captured: list[dict]) -> None:
    _call(_cfg(json_format="json_schema"), json_mode=True, json_schema=_SCHEMA)
    assert captured[0]["response_format"] == {"type": "json_schema", "json_schema": _SCHEMA}


def test_json_schema_format_without_schema_falls_back(captured: list[dict]) -> None:
    _call(_cfg(json_format="json_schema"), json_mode=True)
    assert captured[0]["response_format"] == {"type": "json_object"}


def test_no_response_format_without_json_mode(captured: list[dict]) -> None:
    _call(_cfg(json_format="json_schema"), json_schema=_SCHEMA)
    assert "response_format" not in captured[0]


def test_extra_body_is_forwarded(captured: list[dict]) -> None:
    _call(_cfg(extra_body={"stream": False}))
    assert captured[0]["extra_body"] == {"stream": False}


def test_extra_body_omitted_by_default(captured: list[dict]) -> None:
    _call(_cfg())
    assert "extra_body" not in captured[0]
