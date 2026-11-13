// The back-office shell: thin top bar, the map filling the window, one right panel for the current step.
import { useState } from "react";
import { api, type Network } from "./api/client";
import { MapOverlayProvider, MapView, type MapOverlay } from "./components/MapView";
import { TopBar } from "./components/TopBar";
import { useResource } from "./lib/store";
import { useCase } from "./lib/useCase";
import { OverviewStep } from "./steps/0-overview/OverviewStep";
import { PlanStep } from "./steps/1-plan/PlanStep";
import { DecideStep } from "./steps/2-decide/DecideStep";
import { PublishStep } from "./steps/3-publish/PublishStep";
import { MonitorStep } from "./steps/4-monitor/MonitorStep";
import { ReportStep } from "./steps/5-report/ReportStep";
import type { StepProps } from "./steps/types";

const STEPS: ((p: StepProps) => React.ReactNode)[] = [OverviewStep, PlanStep, DecideStep, PublishStep, MonitorStep, ReportStep];

export function Shell({ step, params }: { step: number; params: URLSearchParams }) {
  const { caseKey, closureId } = useCase(params);
  const network = useResource<Network>("network", () => api.network());
  const zones = useResource<GeoJSON.FeatureCollection>("zones", () => api.zones());
  const [overlay, setOverlay] = useState<MapOverlay>({});
  const Step = STEPS[step] ?? OverviewStep;
  return (
    <div className="app">
      <TopBar step={step} caseKey={caseKey} />
      <MapOverlayProvider value={setOverlay}>
        <main className="workspace">
          <MapView network={network.data} zones={zones.data} overlay={overlay} />
          <Step step={step} caseKey={caseKey} closureId={closureId} />
        </main>
      </MapOverlayProvider>
    </div>
  );
}
