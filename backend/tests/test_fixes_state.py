"""State files are group-readable and writable (0o664), old ones get fixed."""

from __future__ import annotations

import os


def test_write_mode_664(isolated_state):
    from app.common import state

    p = state.write("closures", "cl_test_mode", {"id": "cl_test_mode"})
    assert p.stat().st_mode & 0o777 == 0o664
    p2 = state.path_for("closures", "cl_test_mode", "analysis")
    state.update("closures", "cl_test_mode", lambda old: {"n": 1}, part="analysis")
    assert p2.stat().st_mode & 0o777 == 0o664


def test_fix_modes(isolated_state):
    from app.common import state

    p = state.write("closures", "cl_old", {"id": "cl_old"})
    os.chmod(p, 0o600)
    assert state.fix_modes() >= 1
    assert p.stat().st_mode & 0o777 == 0o664
