"""A-035 复验补充：药盒/药箱等实物核对不是改药。"""
from __future__ import annotations

import pytest

from backend.app.safety import gate


@pytest.mark.parametrize("text", [
    "改为结合药盒/家属协助核对，不涉及任何用药调整。",
    "改为使用药箱提醒，不涉及用药调整。",
    "用分药盒按天摆放，仅做记录核对。",
])
def test_medication_container_reference_is_allowed(text):
    assert gate.check_text(text, generated=True)["allowed"] is True
    assert gate.check_text(text)["allowed"] is True


def test_actual_medication_change_inside_container_is_still_blocked():
    assert gate.check_text("把药盒里的药停掉。", generated=True)["allowed"] is False
