import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { api, type Health } from "../api/client";
import { fmtDateTime } from "../lib/format";
import { navigate, stepHref } from "../lib/router";
import { useResource } from "../lib/store";
import { DataStatus } from "./DataStatus";

export function TopBar({ step, caseKey }: { step: number; caseKey: string | null }) {
  const { t, i18n } = useTranslation();
  const health = useResource<Health>("health", () => api.health());
  const steps = t("steps", { returnObjects: true }) as string[];
  const demoNow = health.data?.demoNow;
  const nav = useRef<HTMLElement>(null);
  // At phone width the step names scroll sideways: keep the current one in view.
  useEffect(() => {
    nav.current?.querySelector('[aria-current="page"]')?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [step]);
  return (
    <header className="topbar">
      <span className="topbar-name">{t("product")}</span>
      <nav ref={nav} aria-label={t("stepsNav")}>
        {steps.map((name, i) => {
          const href = stepHref(i, caseKey);
          return (
            <a
              key={i}
              href={href}
              aria-current={i === step ? "page" : undefined}
              onClick={(e) => {
                e.preventDefault();
                navigate(href);
              }}
            >
              {name}
            </a>
          );
        })}
      </nav>
      <DataStatus />
      {demoNow && <span className="topbar-clock">{t("clock", { time: fmtDateTime(demoNow) })}</span>}
      <button
        type="button"
        className="topbar-lang"
        aria-label={t("langName")}
        onClick={() => void i18n.changeLanguage(i18n.language === "en" ? "ro" : "en")}
      >
        {t("lang")}
      </button>
    </header>
  );
}
