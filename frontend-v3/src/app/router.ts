import { useEffect, useState, type MouseEvent } from "react";

/**
 * Places, not steps. Four things a person opens the platform for:
 *   /app                       Azi: what waits for a person, and the network right now
 *   /app/lucrari               every work
 *   /app/lucrari/<id>/<tab>    one work, the only place with a sequence: impact → perioada → anunt → teren
 *   /app/linii[/<routeId>]     the lines, each with its route and its vehicles
 *   /app/rapoarte              what is reported
 */
export const WORK_TABS = ["impact", "perioada", "anunt", "teren"] as const;
export type WorkTab = (typeof WORK_TABS)[number];

export type Route =
  | { page: "azi" }
  | { page: "lucrari" }
  | { page: "lucrare"; id: string; tab: WorkTab; q?: string }
  | { page: "linii"; routeId?: string }
  | { page: "rapoarte" };

export const HERO = "cl_20261108_16dec";

/** The first version of /app had six global steps; their links keep working. */
const OLD_STEP: Record<string, WorkTab> = { planifici: "impact", decizi: "perioada", publici: "anunt", urmaresti: "teren" };

function read(): Route {
  const [, , a, b, c] = location.pathname.split("/").map(decodeURIComponent);
  const qs = new URLSearchParams(location.search);
  if (a === "lucrari") return b ? { page: "lucrare", id: b, tab: (WORK_TABS as readonly string[]).includes(c) ? (c as WorkTab) : "impact", q: qs.get("q") ?? undefined } : { page: "lucrari" };
  if (a === "linii") return { page: "linii", routeId: b || undefined };
  if (a === "rapoarte" || a === "raportezi") return { page: "rapoarte" };
  if (a in OLD_STEP) return { page: "lucrare", id: qs.get("c") ?? HERO, tab: OLD_STEP[a] };
  return { page: "azi" };
}

const enc = encodeURIComponent;
export function href(r: Route): string {
  switch (r.page) {
    case "azi": return "/app";
    case "lucrari": return "/app/lucrari";
    case "lucrare": return `/app/lucrari/${enc(r.id)}/${r.tab}${r.q ? `?q=${enc(r.q)}` : ""}`;
    case "linii": return r.routeId ? `/app/linii/${enc(r.routeId)}` : "/app/linii";
    case "rapoarte": return "/app/rapoarte";
  }
}

export function useRoute() {
  const [r, setR] = useState(read);
  useEffect(() => {
    const on = () => setR(read());
    addEventListener("popstate", on);
    return () => removeEventListener("popstate", on);
  }, []);
  return r;
}

export function go(r: Route, opts: { replace?: boolean } = {}) {
  const url = href(r);
  if (url === location.pathname + location.search) return;
  history[opts.replace ? "replaceState" : "pushState"](null, "", url);
  dispatchEvent(new PopStateEvent("popstate"));
}

/** Props for a real link that navigates without a page load (new tab and middle click still work). */
export function link(r: Route) {
  return {
    href: href(r),
    onClick: (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      e.preventDefault();
      go(r);
    },
  };
}
