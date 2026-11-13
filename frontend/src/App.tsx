import { useEffect } from "react";
import { QrPage } from "./qr/QrPage";
import { navigate, useLocation } from "./lib/router";
import { Shell } from "./Shell";

export function App() {
  const { path, params } = useLocation();
  const qr = path.match(/^\/a\/([^/]+)\/?$/);
  const step = path.match(/^\/step\/([0-5])\/?$/);
  useEffect(() => {
    if (!qr && !step) navigate("/step/0" + window.location.search);
  }, [qr, step]);
  if (qr) return <QrPage closureId={decodeURIComponent(qr[1])} stopId={params.get("stop")} />;
  if (!step) return null;
  return <Shell step={Number(step[1])} params={params} />;
}
