"""R13: Excel-ready CSV (Romanian Excel: `;` separator, decimal comma, UTF-8 with BOM)."""

from __future__ import annotations

import csv
import io

from fastapi import Response


def num(v) -> str:
    if v is None:
        return ""
    return str(v).replace(".", ",") if isinstance(v, float) else str(v)


def response(name: str, header: list[str], rows: list[list]) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(header)
    for r in rows:
        w.writerow([num(c) for c in r])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
