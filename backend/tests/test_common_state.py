"""The JSON state store: atomic writes, parts, listing, update, delete."""

from __future__ import annotations

import threading

import pytest

from app.common import state


def test_write_read_parts_and_list(isolated_state):
    assert state.read("closures", "cl_a") is None
    state.write("closures", "cl_a", {"id": "cl_a", "n": 1})
    state.write("closures", "cl_a", {"stops": []}, part=state.PART_ANALYSIS)
    state.write("closures", "cl_b", {"id": "cl_b"})
    assert state.read("closures", "cl_a") == {"id": "cl_a", "n": 1}
    assert state.read("closures", "cl_a", "analysis") == {"stops": []}
    assert state.list_ids("closures") == ["cl_a", "cl_b"]          # parts are not listed
    assert [c["id"] for c in state.list_all("closures")] == ["cl_a", "cl_b"]
    assert not list((isolated_state.state_dir / "closures").glob("*.tmp"))


def test_update_is_serialized(isolated_state):
    state.write("scenarios", "sc_1", {"count": 0})

    def bump():
        for _ in range(25):
            state.update("scenarios", "sc_1", lambda old: {"count": old["count"] + 1})

    threads = [threading.Thread(target=bump) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert state.read("scenarios", "sc_1") == {"count": 100}


def test_delete_removes_parts(isolated_state):
    state.write("closures", "cl_x", {"id": "cl_x"})
    state.write("closures", "cl_x", {"totals": {}}, part=state.PART_IMPACT)
    assert state.delete("closures", "cl_x")
    assert state.read("closures", "cl_x", "impact") is None
    assert state.list_ids("closures") == []


@pytest.mark.parametrize("bad", ["../etc", "a/b", "", "x.y"])
def test_rejects_unsafe_ids(isolated_state, bad):
    with pytest.raises(ValueError):
        state.path_for("closures", bad)


def test_new_id_prefix():
    a, b = state.new_id("cl"), state.new_id("cl")
    assert a.startswith("cl_") and a != b
