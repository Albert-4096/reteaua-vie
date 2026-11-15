import { useState, type ReactNode } from "react";
import { Clock, Construction, FileText, Inbox, PlayCircle, Route as RouteIcon } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Logo } from "@/landing/Logo";
import { app, count, day, hhmm } from "./data";
import { MapView } from "./MapView";
import { go, link, useRoute, type Route } from "./router";
import { Lines } from "./pages/Lines";
import { NewWork } from "./pages/NewWork";
import { Reports } from "./pages/Reports";
import { Today } from "./pages/Today";
import { Work } from "./pages/Work";
import { Works } from "./pages/Works";
import { MapCtx, MapSlotCtx, type Layers } from "./ui";
import { Demo } from "@/demo/Demo";

type Place = { id: "azi" | "lucrari" | "linii" | "rapoarte"; label: string; icon: LucideIcon; to: Route };
const PLACES: Place[] = [
  { id: "azi", label: "Azi", icon: Inbox, to: { page: "azi" } },
  { id: "lucrari", label: "Lucrări", icon: Construction, to: { page: "lucrari" } },
  { id: "linii", label: "Linii", icon: RouteIcon, to: { page: "linii" } },
  { id: "rapoarte", label: "Rapoarte", icon: FileText, to: { page: "rapoarte" } },
];

/**
 * Four places in a rail, one panel, one map.
 * Azi is where a dispatcher stays; a work (inside Lucrări) is where the City Hall decides;
 * Linii is the reference; Rapoarte is opened once in a while. The map stays mounted between them.
 */
export function App() {
  const route = useRoute();
  const [layers, setLayers] = useState<Layers>({});
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  // /app/demo plays the pitch on these screens (src/demo); it only navigates, it never writes
  const [demo, setDemo] = useState(() => location.pathname === "/app/demo" || new URLSearchParams(location.search).has("demo"));
  const place = route.page === "lucrare" || route.page === "nou" ? "lucrari" : route.page;
  const hasMap = route.page !== "rapoarte";

  let page: ReactNode;
  if (route.page === "azi") page = <Today />;
  else if (route.page === "lucrari") page = <Works />;
  else if (route.page === "nou") page = <NewWork key={route.c ?? "new"} draftId={route.c} />;
  else if (route.page === "lucrare") page = <Work key={route.id} id={route.id} tab={route.tab} q={route.q} />;
  else if (route.page === "linii") page = <Lines routeId={route.routeId} />;
  else page = <Reports />;

  return (
    <MapCtx.Provider value={setLayers}>
      <MapSlotCtx.Provider value={slot}>
      <div className="flex h-dvh flex-col-reverse bg-background text-foreground md:flex-row">
        <Rail place={place} />
        <main className="flex min-h-0 min-w-0 flex-1 flex-col-reverse md:flex-row">
          <div className={cn("min-h-0 min-w-0 flex-1 bg-card", hasMap && "md:w-[27rem] md:flex-none md:border-r")}>{page}</div>
          <div className={cn("relative h-[36dvh] shrink-0 border-b md:h-auto md:flex-1 md:border-b-0", !hasMap && "hidden")}>
            <MapView {...layers} onClosure={(id) => go({ page: "lucrare", id, tab: "impact" })} onVehicle={(routeId) => go({ page: "linii", routeId })} />
            <Legend l={layers} />
            <div ref={setSlot} />
          </div>
        </main>
      </div>
      {demo && <Demo onExit={() => setDemo(false)} />}
      </MapSlotCtx.Provider>
    </MapCtx.Provider>
  );
}

function Rail({ place }: { place: Place["id"] }) {
  const closures = useApi(app.closures);
  const missing = useApi(app.missing, 60_000);
  // off-route runs are "de verificat" on Azi and stay out of this count until a person confirms one
  const waiting = (closures.data ?? []).filter((c) => c.status !== "published").length
    + (missing.data?.routes ?? []).filter((r) => r.state === "fara_vehicul" && !r.decision).length;

  return (
    <nav aria-label="Secțiunile platformei" className="z-10 flex shrink-0 items-stretch border-t bg-card md:w-[5.25rem] md:flex-col md:items-center md:border-r md:border-t-0 md:py-4">
      <a href="/" aria-label="Rețeaua Vie, pagina de prezentare" className="hidden rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring md:block">
        <Logo className="size-9" />
      </a>
      <ul className="flex flex-1 md:mt-6 md:flex-none md:flex-col md:gap-1">
        {PLACES.map((p) => {
          const on = p.id === place;
          return (
            <li key={p.id} className="flex-1 md:flex-none">
              <a {...link(p.to)} aria-current={on ? "page" : undefined}
                className={cn("group relative flex flex-col items-center gap-1 px-1 py-2 text-[0.6875rem] font-medium outline-none transition-colors md:w-[4.25rem] md:rounded-xl md:py-2.5",
                  "focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring", on ? "text-foreground" : "text-muted-foreground hover:text-foreground")}>
                <span className={cn("relative grid h-8 w-12 place-items-center rounded-full transition-colors", on ? "bg-accent text-accent-foreground" : "group-hover:bg-muted")}>
                  <p.icon className="size-5" strokeWidth={on ? 2.1 : 1.8} />
                  {p.id === "azi" && waiting > 0 && (
                    <span className="tabular absolute -right-0.5 -top-1 grid h-[18px] min-w-[18px] place-items-center rounded-full bg-closure px-1 text-[0.6875rem] font-semibold leading-none text-white ring-2 ring-card">
                      <span aria-hidden>{waiting}</span><span className="sr-only">{count(waiting, "lucru așteaptă", "lucruri așteaptă")} un om</span>
                    </span>
                  )}
                </span>
                {p.label}
              </a>
            </li>
          );
        })}
      </ul>
      <ClockButton />
      <a href="/app/demo" title="Demo ghidat: prezentarea, pe ecranele reale"
        className="hidden flex-col items-center gap-0.5 rounded-xl px-1 py-2 text-[0.6875rem] font-medium leading-tight text-muted-foreground outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring md:mt-1 md:flex md:w-[4.25rem]">
        <PlayCircle className="mb-0.5 size-4" strokeWidth={1.8} />
        Demo
      </a>
    </nav>
  );
}

/** The simulated clock, out of the way; the data sources live behind it. */
function ClockButton() {
  const o = useApi(app.overview);
  return (
    <Popover>
      <PopoverTrigger className="hidden flex-col items-center gap-0.5 rounded-xl px-1 py-2 text-[0.6875rem] leading-tight text-muted-foreground outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring md:mt-auto md:flex md:w-[4.25rem]">
        <Clock className="mb-0.5 size-4" strokeWidth={1.8} />
        <span className="tabular font-semibold text-foreground">{o.data ? hhmm(o.data.at) : "–"}</span>
        <span className="tabular">{o.data ? day(o.data.at) : ""}</span>
        <span>simulat</span>
      </PopoverTrigger>
      <PopoverContent side="right" align="end" sideOffset={10} className="w-80 text-sm leading-relaxed">
        <p className="font-medium">Ceas simulat</p>
        <p className="mt-1 text-muted-foreground">Lucrările sunt arătate ca în duminica de 8 noiembrie 2026, ziua lucrării de pe Bd. 16 Decembrie 1989. Vehiculele de pe hartă vin din datele live ale Primăriei, acum.</p>
        <p className="mt-3 font-medium">Surse</p>
        <p className="mt-1 text-muted-foreground">Orarul SMTT (GTFS), endpointurile Primăriei, anunțurile STPT, pozițiile vehiculelor înregistrate de noi la 15 s. Populația: model GHSL 2020.</p>
      </PopoverContent>
    </Popover>
  );
}

/** Only what is on the map right now, in words. */
function Legend({ l }: { l: Layers }) {
  const tones = new Set((l.stops ?? []).map((s) => s.tone));
  const items: [ReactNode, string][] = [];
  if (l.closures?.length) items.push([<span className="h-1 w-5 rounded-full" style={{ backgroundImage: "repeating-linear-gradient(90deg, var(--closure) 0 5px, transparent 5px 8px)" }} />, "lucrare"]);
  if (l.segment?.length) items.push([<span className="h-[7px] w-5 rounded-full border-2 border-foreground bg-white" />, "porțiunea întrebată"]);
  if (tones.has("closed")) items.push([<span className="size-2.5 rounded-full bg-closure ring-2 ring-white" />, "nu oprește"]);
  if (tones.has("ask")) items.push([<span className="size-2.5 rounded-full border-2 border-foreground bg-white" />, "de hotărât"]);
  if (tones.has("served")) items.push([<span className="size-2 rounded-full border-[1.5px] border-[#5b6a64] bg-white" />, "oprește"]);
  if (l.parking?.length) items.push([<span className="h-1 w-5 rounded-full bg-foreground ring-2 ring-white" />, "stradă cu parcare cu plată"]);
  if (l.detour?.length) items.push([<span className="h-0.5 w-5" style={{ backgroundImage: "repeating-linear-gradient(90deg, var(--foreground) 0 5px, transparent 5px 8px)" }} />, "linie temporară"]);
  if (l.ghost?.length) items.push([<span className="h-[3px] w-5" style={{ backgroundImage: "repeating-linear-gradient(90deg, #4d897f 0 3px, transparent 3px 7px)" }} />, "linie fără vehicul în datele live"]);
  if (l.vehicles?.length) items.push([<span className="size-2.5 rounded-full bg-[#4d897f] ring-2 ring-white" />, l.recorded ? "vehicul, din înregistrare" : "vehicul, date live"]);
  if (!items.length) return null;
  return (
    <ul aria-label="Legenda hărții" className={cn("pointer-events-none absolute left-3 top-3 flex max-w-[calc(100%-1.5rem)] flex-wrap gap-x-4 gap-y-1.5 rounded-lg border bg-card/95 px-3 py-2 text-xs text-foreground/80 shadow-card", l.recorded && "max-md:hidden")}>
      {items.map(([swatch, word]) => <li key={word} className="flex items-center gap-2">{swatch}{word}</li>)}
    </ul>
  );
}
