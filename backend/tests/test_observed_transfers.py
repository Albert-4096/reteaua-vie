"""A11 transfers: hubs and connections on synthetic data built here."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.observed import transfers as tr


def test_find_hubs_groups_same_name_within_400_m():
    names = {"1": "Piața Mare (Nord)", "2": "Piața Mare (Sud)", "3": "Piața Mare (Departe)", "4": "Altă stație"}
    xy = {"1": (0.0, 0.0), "2": (150.0, 0.0), "3": (2000.0, 0.0), "4": (10.0, 0.0)}
    routes = {"1": {"A", "B"}, "2": {"C"}, "3": {"D"}, "4": {"A", "B", "C", "D"}}
    hubs = tr.find_hubs(names, xy, routes)
    assert hubs["Piața Mare"] == ["1", "2"]           # 3 is too far; 1+2 serve 3 lines
    assert hubs["Altă stație"] == ["4"]
    assert tr.slug("Piața Timișoara 700") == "piata-timisoara-700"


def test_connections_met_missed_and_unrecorded():
    walk = {("X", "Y"): 120.0}
    arr = pd.DataFrame([
        ("a1", "d", "A", "X", 1000.0, 1000.0),   # on time: catches the 1300 departure
        ("a2", "d", "A", "X", 5300.0, 5000.0),   # 5 min late: the planned 5300 left already, takes 5900
        ("a3", "d", "A", "X", 9000.0, 9000.0),   # a B departure around then was not recorded: not counted
    ], columns=["trip_id", "service_date", "route_id", "stop_id", "t", "s"])
    dep = pd.DataFrame([
        ("b1", "d", "B", 0, "Y", 1300.0, 1310.0),
        ("b2", "d", "B", 0, "Y", 5300.0, 5350.0),
        ("b3", "d", "B", 0, "Y", 5900.0, 5900.0),
        ("b4", "d", "B", 0, "Y", 9300.0, np.nan),
    ], columns=["trip_id", "service_date", "route_id", "direction_id", "stop_id", "p", "o"])
    c = tr.connections(arr, dep, walk).set_index("block")
    assert list(c.index) == ["a1|d", "a2|d"]
    assert not c.loc["a1|d", "missed"] and c.loc["a1|d", "planned"] == 300 and c.loc["a1|d", "real"] == 310
    assert c.loc["a2|d", "missed"] and c.loc["a2|d", "planned"] == 300 and c.loc["a2|d", "real"] == 600
