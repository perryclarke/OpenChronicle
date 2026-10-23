"""capture/event_dispatcher.py: what a watcher event passes on to the capture."""

from __future__ import annotations

from openchronicle.capture.event_dispatcher import EventDispatcher


def _dispatch(event: dict) -> list[dict]:
    triggers: list[dict] = []
    EventDispatcher(triggers.append).on_event(event)
    return triggers


def test_text_input_trigger_carries_the_typed_element() -> None:
    element = {"role": "AXTextArea", "subrole": "", "title": "", "identifier": "", "value": "on my way"}
    triggers = _dispatch({
        "event_type": "UserTextInput", "bundle_id": "com.tinyspeck.slackmacgap",
        "window_title": "Jason Blazick (DM)", "details": {"reason": "debounce", "element": element},
    })
    assert triggers == [{
        "event_type": "UserTextInput", "bundle_id": "com.tinyspeck.slackmacgap",
        "window_title": "Jason Blazick (DM)", "element": element,
    }]


def test_click_trigger_does_not_carry_an_element() -> None:
    triggers = _dispatch({
        "event_type": "UserMouseClick", "bundle_id": "b", "window_title": "w",
        "details": {"element": {"role": "AXButton", "value": "Send"}},
    })
    assert len(triggers) == 1 and "element" not in triggers[0]
