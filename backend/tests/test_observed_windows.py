"""L2 measured windows: cut stretches, detour routing and path minutes (synthetic data built here)."""

from __future__ import annotations

import networkx as nx
import numpy as np

from app.observed import detour_cost as dc
from app.observed import window_cost as wc


def test_runs_cut_between_served_stops_and_terminals():
    cuts, terminal = [], []
    order = list("ABCDEFG")
    # C lost, and the closed street runs between E and F (no stop on it)
    wc._runs(order, {"C"}, {4}, "R_AB_1", 0, cuts, terminal)
    assert [(c.a, c.b, c.cut) for c in cuts] == [("B", "D", ["C"]), ("E", "F", [])]
    assert terminal == []
    cuts, terminal = [], []
    wc._runs(order, {"F", "G"}, set(), "R_AB_1", 0, cuts, terminal)   # cut to the end of the line
    assert cuts == [] and terminal == [("R_AB_1", 0)]


def _graph() -> wc.Graph:
    # a square A(0,0) - B(100,0) - C(100,100) - D(0,100); the direct A-B street is closed
    g = nx.DiGraph()
    xy = {1: (0.0, 0.0), 2: (100.0, 0.0), 3: (100.0, 100.0), 4: (0.0, 100.0)}
    for u, v, seg in ((1, 4, 0), (4, 3, 1), (3, 2, 2)):
        g.add_edge(u, v, w=100.0, seg=seg)
    nodes = np.array(sorted(xy))
    return wc.Graph(g, xy, nodes, np.array([xy[n] for n in nodes]))


def test_route_detour_goes_around(monkeypatch):
    class D:
        u = np.array([1, 4, 3])
        v = np.array([4, 3, 2])
        xy = [np.array([[0, 0], [0, 100]]), np.array([[0, 100], [100, 100]]), np.array([[100, 100], [100, 0]])]

    from app.m4_access import detour

    monkeypatch.setattr(detour, "drive_edges", lambda: D)
    line, segs = wc.route_detour(_graph(), (0.0, 0.0), (100.0, 0.0))
    assert segs == [0, 1, 2] and round(line.length) == 300


def test_path_time_needs_measured_coverage():
    def obs(paces):
        n = len(paces)
        return dc.StreetObs(pace=np.array(paces, dtype=float), hour=np.full(n, 10), block=np.arange(n),
                            day=np.full(n, 5))

    m = dc.StreetMatch(slice_len=[100.0] * 10, slice_unit=[1] * 9 + [2], slice_len_arr=np.full(10, 100.0),
                       units={1: obs([0.1, 0.1, 0.1]), 2: obs([])}, area=obs([]), routes_used=set(), seg=None)
    t, share, n = wc._path_time(m, 5, 10, None)
    assert share == 0.9 and n == 3
    assert abs(t - 100.0) < 1e-6           # 900 m at 0.1 s/m, the unmeasured 100 m at the same mean pace
    t, share, _ = wc._path_time(m, 5, 14, None)   # nothing measured at 14:00 on that day
    assert np.isnan(t) and share == 0.0
    m.slice_unit = [1] * 7 + [2] * 3        # 70 % measured: no number
    assert np.isnan(wc._path_time(m, 5, 10, None)[0])
