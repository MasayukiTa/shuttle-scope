"""Public status page template: live refresh of fields and modal focus trap.

Audit #940: the 60 s poll only compared overall/counts, so checked_at and the
component status/detail never refreshed. Audit #937: the day-detail modal has
aria-modal=true but did not keep Tab focus inside the dialog.
The page is a Jinja template with inline vanilla JS, so these tests read the
template source like the sibling status tests do.
"""
from __future__ import annotations

import pathlib

_TEMPLATE = (
    pathlib.Path(__file__).resolve().parents[1] / "templates" / "public" / "status.html.j2"
)


def _src() -> str:
    return _TEMPLATE.read_text(encoding="utf-8")


def test_poll_refreshes_checked_at_and_component_fields_in_place():
    src = _src()
    assert 'id="ss-checked-at"' in src
    assert 'data-key="{{ c.key }}"' in src
    poll = src[src.index("function poll()"): src.index("setInterval(poll")]
    assert "ss-checked-at" in poll
    assert "d.components" in poll
    assert "ss-comp-badge" in poll
    assert "ss-comp-detail" in poll


def test_modal_keydown_traps_tab_focus():
    src = _src()
    handler = src[src.index("document.addEventListener('keydown'"):]
    assert "e.key==='Tab'" in handler
    assert "e.shiftKey" in handler
    assert "first.focus()" in handler and "last.focus()" in handler
