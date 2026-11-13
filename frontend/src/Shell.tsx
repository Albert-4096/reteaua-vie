// The back-office shell: thin top bar, the map filling the window, one right panel for the current step.
import { lazy, Suspense, useState } from "react";
import { api, type Network } from "./api/client";
import { MapOverlayProvider, MapView, type MapOverlay } from "./components/MapView";
import { TopBar } from "./components/TopBar";
import { useResource } from "./lib/store";
import { useCase } from "./lib/useCase";
import type { StepProps } from "./steps/types";

// Each step loads on its own, so a step still in progress cannot break the others.
const STEPS: React.LazyExoticComponent<(p: StepProps) => React.ReactNode>[] = [
  lazy(() => import("./steps/0-overview/OverviewStep").then((m) => ({ default: m.OverviewStep }))),
  lazy(() => import("./steps/1-plan/PlanStep").then((m) => ({ default: m.PlanStep }))),
  lazy(() => import("./steps/2-decide/DecideStep").then((m) => ({ default: m.DecideStep }))),
  lazy(() => import("./steps/3-publish/PublishStep").then((m) => ({ default: m.PublishStep }))),
  lazy(() => import("./steps/4-monitor/MonitorStep").then((m) => ({ default: m.MonitorStep }))),
  lazy(() => import("./steps/5-report/ReportStep").then((m) => ({ default: m.ReportStep }))),
];

export function Shell({ step, params }: { step: number; params: URLSearchParams }) {
  const { caseKey, closureId } = useCase(params);
  const network = useResource<Network>("network", () => api.network());
  const zones = useResource<GeoJSON.FeatureCollection>("zones", () => api.zones());
  const [overlay, setOverlay] = useState<MapOverlay>({});
  const Step = STEPS[step] ?? STEPS[0];
  return (
    <div className="app">
      <TopBar step={step} caseKey={caseKey} />
      <MapOverlayProvider value={setOverlay}>
        <main className="workspace">
          <MapView network={network.data} zones={zones.data} overlay={overlay} />
          <Suspense fallback={<aside className="panel" />}>
            <Step step={step} caseKey={caseKey} closureId={closureId} />
          </Suspense>
        </main>
      </MapOverlayProvider>
    </div>
  );
}
