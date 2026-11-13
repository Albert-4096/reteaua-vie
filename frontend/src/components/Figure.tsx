// Every number on screen goes through <Figure>. Its source and date show on hover, focus or tap.
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Provenance } from "../api/client";
import { fmtDateTime, fmtNumber } from "../lib/format";

type Props = {
  value: number | null | undefined;
  label?: string;
  unit?: string;
  provenance: Provenance[] | null | undefined;
  /** One sentence on how the number is made (e.g. Impact.method). */
  method?: string | null;
  inline?: boolean;
};

export function Figure({ value, label, unit, provenance, method, inline }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const id = useId();
  const shown = fmtNumber(value);
  return (
    <span className={inline ? "figure figure-inline" : "figure"} onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        className="figure-value"
        aria-describedby={id}
        aria-expanded={open}
        onMouseEnter={() => setOpen(true)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen((o) => !o)}
      >
        {shown ?? t("unknown")}
        {shown && unit ? ` ${unit}` : ""}
      </button>
      {label && <span className="figure-label">{label}</span>}
      <span id={id} role="tooltip" className={open ? "figure-source" : "visually-hidden"}>
        <strong>{t("source")}: </strong>
        {(provenance ?? []).length === 0 && t("unknown")}
        {(provenance ?? []).map((p, i) => (
          <span key={i}>
            {i > 0 && "; "}
            {p.source}
            {p.version ? ` ${p.version}` : ""}
            {p.fetchedAt ? `, ${t("sourceDate", { date: fmtDateTime(p.fetchedAt) })}` : ""}
            {p.note ? ` (${p.note})` : ""}
          </span>
        ))}
        {method && (
          <span>
            <br />
            <strong>{t("method")}: </strong>
            {method}
          </span>
        )}
      </span>
    </span>
  );
}
