import { useTranslation } from "react-i18next";
import { navigate } from "../lib/router";
import { useCases } from "../lib/useCase";
import { tr } from "../lib/format";
import { LoadState, Panel } from "./Panel";

/** Shown by a step that needs a closure when the URL names none. */
export function CasePicker({ step }: { step: number }) {
  const { t } = useTranslation();
  const cases = useCases();
  return (
    <Panel title={t("noCase")} sentence={t("noCaseBody")}>
      <LoadState {...cases} />
      <ul className="list">
        {(cases.data ?? []).map((c) => {
          const key = c.id.replace(/^case_/, "");
          const href = `/step/${step}?case=${encodeURIComponent(key)}`;
          return (
            <li key={c.id}>
              <a
                href={href}
                onClick={(e) => {
                  e.preventDefault();
                  navigate(href);
                }}
              >
                {tr(c.title)}
              </a>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}
