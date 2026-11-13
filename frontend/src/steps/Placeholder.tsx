import { useTranslation } from "react-i18next";
import { InProgress, Panel } from "../components/Panel";
import type { StepProps } from "./types";

/** Steps that are not built yet show their name and „în lucru”, never numbers (D-011). */
export function Placeholder({ step }: StepProps) {
  const { t } = useTranslation();
  const steps = t("steps", { returnObjects: true }) as string[];
  return (
    <Panel title={steps[step]}>
      <InProgress />
    </Panel>
  );
}
