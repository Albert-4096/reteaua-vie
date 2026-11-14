import { useEffect, useState } from "react";

export const STEPS = [
  { id: "ansamblu", label: "Ansamblu", hint: "Ce e închis acum" },
  { id: "planifici", label: "Planifici", hint: "Cine pierde serviciul" },
  { id: "decizi", label: "Decizi", hint: "Fereastra și varianta" },
  { id: "publici", label: "Publici", hint: "Fișierele pentru toți" },
  { id: "urmaresti", label: "Urmărești", hint: "Ce au făcut vehiculele" },
  { id: "raportezi", label: "Raportezi", hint: "Obligațiile UE" },
] as const;
export type StepId = (typeof STEPS)[number]["id"];

export const DEFAULT_CLOSURE = "cl_20261108_16dec";

function read() {
  const [, , step] = location.pathname.split("/");
  const c = new URLSearchParams(location.search).get("c") ?? DEFAULT_CLOSURE;
  return { step: (STEPS.some((s) => s.id === step) ? step : "ansamblu") as StepId, closureId: c };
}

/** Path router: /app/<step>?c=<closureId>. */
export function useRoute() {
  const [r, setR] = useState(read);
  useEffect(() => {
    const on = () => setR(read());
    addEventListener("popstate", on);
    return () => removeEventListener("popstate", on);
  }, []);
  return r;
}

export function go(step: StepId, closureId?: string) {
  const c = closureId ?? new URLSearchParams(location.search).get("c") ?? DEFAULT_CLOSURE;
  history.pushState(null, "", `/app/${step}?c=${encodeURIComponent(c)}`);
  dispatchEvent(new PopStateEvent("popstate"));
  document.getElementById("content")?.scrollTo({ top: 0 });
}
