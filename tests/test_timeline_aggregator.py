"""timeline/aggregator.py: capture-filename parsing and window selection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from openchronicle.capture import scheduler as scheduler_mod
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
