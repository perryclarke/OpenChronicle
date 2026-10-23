"""timeline/aggregator.py: capture-filename parsing, window selection, and block output."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from openchronicle import config as config_mod
from openchronicle.capture import scheduler as scheduler_mod
from openchronicle.store import fts
from openchronicle.timeline import aggregator


@pytest.mark.parametrize(
    "iso",
    [
        "2026-04-21T17:07:32+08:00",
        "2026-10-21T12:24:10-07:00",
        "2026-10-21T12:24:10+00:00",
        "2026-10-21T12:24:10-03:30",
    ],
)
def test_stem_round_trips_scheduler_filename(iso: str) -> None:
    stem = scheduler_mod._safe_filename(iso)
    parsed = aggregator._stem_to_dt(stem)
    assert parsed == datetime.fromisoformat(iso)
    assert parsed is not None and parsed.tzinfo is not None


def test_stem_accepts_m_prefixed_negative_offset() -> None:
    parsed = aggregator._stem_to_dt("2026-10-21T12-24-10m07-00")
    assert parsed == datetime.fromisoformat("2026-10-21T12:24:10-07:00")


def test_negative_offset_stem_compares_with_aware_window() -> None:
    tz = timezone(timedelta(hours=-7))
    start = datetime(2026, 10, 21, 12, 24, tzinfo=tz)
    end = start + timedelta(minutes=1)
    assert aggregator._capture_stem_in_window("2026-10-21T12-24-10-07-00", start, end)
    assert not aggregator._capture_stem_in_window("2026-10-21T12-25-10-07-00", start, end)


def test_captures_in_window_with_negative_offset(ac_root: Path) -> None:
    from openchronicle import paths

    buf = paths.capture_buffer_dir()
    for iso in (
        "2026-10-21T12:23:59-07:00",
        "2026-10-21T12:24:10-07:00",
        "2026-10-21T12:24:55-07:00",
        "2026-10-21T12:25:00-07:00",
    ):
        (buf / f"{scheduler_mod._safe_filename(iso)}.json").write_text("{}")

    tz = timezone(timedelta(hours=-7))
    start = datetime(2026, 10, 21, 12, 24, tzinfo=tz)
    files = aggregator.captures_in_window(start, start + timedelta(minutes=1))

    assert [p.stem for p in files] == [
        "2026-10-21T12-24-10-07-00",
        "2026-10-21T12-24-55-07-00",
    ]


# ─── block output guards ──────────────────────────────────────────────────

_TZ = timezone(timedelta(hours=-7))
_START = datetime(2026, 10, 22, 15, 17, tzinfo=_TZ)


def _write_capture(
    buf: Path, *, second: int, app: str, title: str, text: str = "", typed: str = "",
) -> None:
    ts = (_START + timedelta(seconds=second)).isoformat()
    data: dict = {
        "timestamp": ts,
        "window_meta": {"app_name": app, "title": title, "bundle_id": "com.test." + app.lower()},
        "visible_text": text,
    }
    if typed:
        data["focused_element"] = {
            "role": "AXTextArea", "is_editable": True, "value": typed, "value_length": len(typed),
        }
    (buf / f"{scheduler_mod._safe_filename(ts)}.json").write_text(json.dumps(data))


def _block_entries(ac_root: Path, monkeypatch: pytest.MonkeyPatch, llm_entries: list[str]) -> list[str]:
    monkeypatch.setenv("OPENCHRONICLE_LLM_MOCK", "1")
    monkeypatch.setenv("OPENCHRONICLE_LLM_MOCK_JSON", json.dumps({"entries": llm_entries}))
    cfg = config_mod.load(ac_root / "config.toml")
    with fts.cursor() as conn:
        block = aggregator.produce_block_for_window(
            cfg, conn, start=_START, end=_START + timedelta(minutes=1),
        )
    assert block is not None
    return block.entries


def test_block_drops_entry_for_app_not_on_screen(ac_root: Path, monkeypatch) -> None:
    from openchronicle import paths

    _write_capture(paths.capture_buffer_dir(), second=5, app="Terminal", title="nimbus-macos")
    entries = _block_entries(ac_root, monkeypatch, [
        "[Terminal] nimbus-macos: read build output.",
        "[Google Chrome] ACME Q3 roadmap (https://docs.example/roadmap): read the document.",
    ])
    assert entries == ["[Terminal] nimbus-macos: read build output."]


def test_block_app_match_is_case_insensitive(ac_root: Path, monkeypatch) -> None:
    from openchronicle import paths

    _write_capture(paths.capture_buffer_dir(), second=5, app="Slack", title="Jason Blazick (DM)")
    entries = _block_entries(ac_root, monkeypatch, ["[slack] Jason Blazick (DM): read messages."])
    assert entries == ["[slack] Jason Blazick (DM): read messages."]


def test_block_drops_prompt_example_text_not_on_screen(ac_root: Path, monkeypatch) -> None:
    from openchronicle import paths

    _write_capture(paths.capture_buffer_dir(), second=5, app="Slack", title="Jason Blazick (DM)")
    entries = _block_entries(ac_root, monkeypatch, [
        "[Slack] Jason Blazick (DM): opened the conversation.",
        '[Slack] Jason Blazick (DM): user typed: "milk, eggs, flour, butter".',
    ])
    assert entries == ["[Slack] Jason Blazick (DM): opened the conversation."]


def test_block_keeps_example_like_text_that_was_really_typed(ac_root: Path, monkeypatch) -> None:
    from openchronicle import paths

    _write_capture(
        paths.capture_buffer_dir(), second=5, app="Notes", title="Shopping list",
        typed="milk, eggs, flour, butter",
    )
    entry = '[Notes] Shopping list: user drafted a list, latest version "milk, eggs, flour, butter".'
    assert _block_entries(ac_root, monkeypatch, [entry]) == [entry]


def test_block_falls_back_to_heuristic_when_every_entry_is_dropped(ac_root: Path, monkeypatch) -> None:
    from openchronicle import paths

    _write_capture(paths.capture_buffer_dir(), second=5, app="Terminal", title="nimbus-macos")
    entries = _block_entries(ac_root, monkeypatch, [
        "[Google Chrome] ACME Q3 roadmap: read the document. Involving: Alice.",
    ])
    assert entries == ["[Terminal] worked in window 'nimbus-macos', involving —"]


def test_example_markers_match_the_prompt() -> None:
    from openchronicle.prompts import load as load_prompt

    prompt = load_prompt("timeline_block.md")
    missing = [m for m in aggregator._PROMPT_EXAMPLE_MARKERS if m not in prompt]
    assert not missing, f"update _PROMPT_EXAMPLE_MARKERS to match the prompt example: {missing}"


def _captured_prompt(ac_root: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    from openchronicle.writer import llm as llm_mod

    seen: list[str] = []

    def fake_call_llm(cfg, stage, *, messages, tools=None, json_mode=False, json_schema=None):
        seen.append(messages[0]["content"])
        raise RuntimeError("stop after capturing the prompt")

    monkeypatch.setattr(llm_mod, "call_llm", fake_call_llm)
    cfg = config_mod.load(ac_root / "config.toml")
    with fts.cursor() as conn:
        aggregator.produce_block_for_window(cfg, conn, start=_START, end=_START + timedelta(minutes=1))
    return seen[0]


def test_prompt_puts_window_activity_after_the_example(ac_root: Path, monkeypatch) -> None:
    from openchronicle import paths

    _write_capture(paths.capture_buffer_dir(), second=5, app="Terminal", title="UNIQUE-WINDOW-TITLE")
    prompt = _captured_prompt(ac_root, monkeypatch)
    assert prompt.index("### Example") < prompt.index("UNIQUE-WINDOW-TITLE")
    assert prompt.rstrip().endswith("no markdown fences and no surrounding prose.")


def test_prompt_states_how_many_typed_snapshots_the_window_has(ac_root: Path, monkeypatch) -> None:
    from openchronicle import paths

    buf = paths.capture_buffer_dir()
    _write_capture(buf, second=5, app="Slack", title="Jason Blazick (DM)", typed="on my way")
    _write_capture(buf, second=9, app="Terminal", title="nimbus-macos")
    prompt = _captured_prompt(ac_root, monkeypatch)
    assert "Authored-text snapshots (`(editing)` lines) in this window: 1." in prompt


def test_focused_value_that_repeats_the_window_title_is_omitted() -> None:
    title = "nimbus-macos — OC | Xcodebuild Lightroom release log erro… — opencode --continue — 114×56"
    data = {
        "timestamp": "2026-10-21T14:13:33-07:00",
        "window_meta": {"app_name": "Terminal", "title": title, "bundle_id": "com.apple.Terminal"},
        "focused_element": {"role": "AXStaticText", "is_editable": False, "value": title, "value_length": 89},
    }
    events_text, _ = aggregator._format_events([(Path("x.json"), data)])
    assert events_text.count(title) == 1
    assert "len=" not in events_text
