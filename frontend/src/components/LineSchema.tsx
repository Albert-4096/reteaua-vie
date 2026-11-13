// The stops of a line's affected section, in order. Lost stops are struck through; the status is also a word for screen readers.
import { useTranslation } from "react-i18next";
import type { SchemaStop } from "../lib/geo";

export function LineSchema({ stops, label }: { stops: SchemaStop[]; label: string }) {
  const { t } = useTranslation();
  if (stops.length === 0) return null;
  return (
    <ol className="schema" aria-label={label}>
      {stops.map((s, i) => (
        <li key={i} className={s.status === "lost" ? "lost" : s.status === "unsure" ? "unsure" : undefined}>
          {s.name}
          {s.status === "lost" && <span className="visually-hidden"> ({t("plan.srLost")})</span>}
          {s.status === "unsure" && <span className="visually-hidden"> ({t("plan.srUnsure")})</span>}
          {s.status === "partial" && (
            <span className="dir-note st-lost">
              {s.lostTowards.map((h) => t("plan.lostOnlyTowards", { headsign: h })).join("; ")}
            </span>
          )}
        </li>
      ))}
    </ol>
  );
}
