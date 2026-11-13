// A tiny history router: the app has only /step/0..5 and the public QR page /a/{closureId}.
import { useEffect, useState } from "react";

export type Loc = { path: string; params: URLSearchParams };

const read = (): Loc => ({ path: window.location.pathname, params: new URLSearchParams(window.location.search) });

export function navigate(to: string) {
  window.history.pushState(null, "", to);
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo(0, 0);
}

export function useLocation(): Loc {
  const [loc, setLoc] = useState(read);
  useEffect(() => {
    const on = () => setLoc(read());
    window.addEventListener("popstate", on);
    return () => window.removeEventListener("popstate", on);
  }, []);
  return loc;
}

/** Step links keep the prepared case (`?case=16dec`). */
export function stepHref(step: number, caseKey: string | null) {
  return `/step/${step}` + (caseKey ? `?case=${encodeURIComponent(caseKey)}` : "");
}
