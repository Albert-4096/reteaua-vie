import { useState } from "react";
import { useTranslation } from "react-i18next";
import { navigate } from "../lib/router";
import { useCases } from "../lib/useCase";
import { tr } from "../lib/format";
import { LoadState, Panel } from "./Panel";
import { PasteNotice } from "./paste-notice/PasteNotice";
import { StreetSearch } from "./street-search/StreetSearch";
import { S } from "./street-search/strings";

/** Shown by a step that needs a closure when the URL names none. Step 1 also takes a pasted STPT notice (R1). */
export function CasePicker({ step }: { step: number }) {
  const { t } = useTranslation();
  const [input, setInput] = useState<"notice" | "street">("notice");
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
      {step === 1 && <>
        <div className="street-input-method" role="group" aria-label={tr(S.method)}>
          <button type="button" className="btn" aria-pressed={input === "notice"} onClick={() => setInput("notice")}>{tr(S.notice)}</button>
          <button type="button" className="btn" aria-pressed={input === "street"} onClick={() => setInput("street")}>{tr(S.street)}</button>
        </div>
        {input === "notice" ? <PasteNotice /> : <StreetSearch />}
      </>}
    </Panel>
  );
}
