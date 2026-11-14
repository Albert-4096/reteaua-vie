import { useMemo, useState } from "react";
import type { Position } from "geojson";
import { LineBadge } from "@/landing/LineBadge";
import { Plus } from "lucide-react";
import { app, losses, phase, place, spread, useLoad, when, type ClosureSummary } from "../data";
import { link } from "../router";
import { Loading, Panel, Problem, Tag, Title, useMapLayers, type Layers } from "../ui";

const coords = (c: ClosureSummary): Position[] => (!c.geometry ? [] : c.geometry.type === "LineString" ? c.geometry.coordinates : c.geometry.coordinates.flat());

/** Every work the platform knows, the ones that still need a person first. */
export function Works() {
  const o = useLoad(app.overview);
  const works = useLoad(app.works);
  const [hover, setHover] = useState<string | null>(null);
  const now = o.data?.at;
  const list = useMemo(() => [...(works.data ?? [])].sort((a, b) => Number(a.status === "published") - Number(b.status === "published") || Date.parse(b.window.start) - Date.parse(a.window.start)), [works.data]);

  const layers = useMemo<Layers>(() => ({
    fit: { key: `works:${list.length}`, points: list.flatMap(coords), maxZoom: 13.4 },
    closures: list.map((c) => ({ id: c.id, geometry: c.geometry, selected: c.id === hover })),
    highlight: list.find((c) => c.id === hover)?.routeIds ?? [],
    labels: spread(list.flatMap((c) => {
      const p = coords(c), mid = p[Math.floor(p.length / 2)];
      return mid ? [{ id: c.id, lon: mid[0], lat: mid[1], text: place(c.title.ro), tone: "work" as const }] : [];
    })),
  }), [list, hover]);
  useMapLayers(layers);

  return (
    <Panel head={<Title sub="Fiecare lucrare care închide o stradă cu transport public, de la anunț până pe teren.">Lucrări</Title>}>
      {works.error ? <Problem>Lucrările nu s-au încărcat ({works.error}). Reîncărcați pagina.</Problem> : !works.data ? <Loading rows={3} /> : (
        <ul className="-mx-2 -mt-1 divide-y">
          {list.map((c) => (
            <li key={c.id}>
              <a {...link(c.status === "draft" ? { page: "nou", c: c.id } : { page: "lucrare", id: c.id, tab: "impact" })} onPointerEnter={() => setHover(c.id)} onPointerLeave={() => setHover(null)} onFocus={() => setHover(c.id)} onBlur={() => setHover(null)}
                className="block rounded-lg px-2 py-4 outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring">
                <span className="block font-medium leading-snug">{c.title.ro}</span>
                <span className="tabular mt-1 block text-sm text-muted-foreground">{when(c.window)}{now ? ` · ${phase(c.window, now)}` : ""}</span>
                <span className="mt-2.5 flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
                  {c.status === "published" ? <Tag tone="green">Publicată</Tag> : c.status === "draft" ? <Tag>Ciornă</Tag> : <Tag tone="closure">Nepublicată</Tag>}
                  <span className="flex gap-1">{c.routeIds.slice(0, 6).map((r) => <LineBadge key={r} routeId={r} />)}</span>
                  <span className="tabular ml-auto text-sm text-muted-foreground">{losses(c)}</span>
                </span>
              </a>
            </li>
          ))}
          <li>
            <a {...link({ page: "nou" })} className="flex items-center gap-2 rounded-lg px-2 py-3.5 text-sm font-medium text-foreground/80 outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
              <Plus className="size-4" /> Lucrare nouă, din anunț
            </a>
          </li>
        </ul>
      )}
    </Panel>
  );
}
