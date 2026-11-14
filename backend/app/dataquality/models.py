"""R12 response types (CONTRACT v2.16)."""

from __future__ import annotations

from typing import Literal

from app.models.base import I18n, Model, Provenance


class QualityRow(Model):
    id: str
    title: I18n
    status: Literal["de_verificat", "in_regula", "indisponibil"]
    basis: Literal["calculat", "manual"]  # calculat = computed now from data on disk; manual = a dated observation by us
    found: int | None  # items to check
    of: int | None  # out of how many
    detail: list[str]  # first items, capped at 15
    owner: Literal["SMTT", "STPT", "Primăria", "Timpark"]
    unlocks: I18n  # the platform number this would make exact
    request: I18n  # a neutral text a person can send
    provenance: list[Provenance]


class DataQuality(Model):
    generatedAt: str
    rows: list[QualityRow]
    provenance: list[Provenance]
