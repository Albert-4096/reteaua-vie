// The one right panel: a title, one sentence, the step's content and one primary action at the bottom.
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { ApiError } from "../api/client";

type Props = { title: ReactNode; sentence?: ReactNode; children?: ReactNode; foot?: ReactNode };

export function Panel({ title, sentence, children, foot }: Props) {
  return (
    <aside className="panel" aria-label="Panou">
      <div className="panel-body">
        <div>
          <h1>{title}</h1>
          {sentence && <p className="muted" style={{ marginTop: "var(--sp-2)" }}>{sentence}</p>}
        </div>
        {children}
      </div>
      {foot && <div className="panel-foot">{foot}</div>}
    </aside>
  );
}

/** A part whose endpoint is not real yet: the words „în lucru”, never numbers (D-011). */
export function InProgress() {
  const { t } = useTranslation();
  return (
    <div>
      <p>
        <strong>{t("inProgress")}</strong>
      </p>
      <p className="muted small">{t("inProgressBody")}</p>
    </div>
  );
}

export function LoadState({ loading, pending, error }: { loading?: boolean; pending?: boolean; error?: ApiError }) {
  const { t } = useTranslation();
  if (error) return <p className="error-msg">{t("errorLoad", { msg: `${error.code}: ${error.message}` })}</p>;
  if (pending) return <p className="state-msg" role="status">{t("computing")}</p>;
  if (loading) return <p className="state-msg" role="status">{t("loading")}</p>;
  return null;
}
