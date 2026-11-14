// Varianta 2: sidebar, the issue list as an inbox, the selected issue with its own map.
import { useState } from "react";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { Separator } from "@/components/ui/separator";
import type { Acum, Issue } from "@/lib/acum";
import { AppSidebar } from "@/components/rv/app-sidebar";
import { IssueActions, IssueDetail, IssueRow, KpiStrip, LiveClock } from "@/components/rv/parts";
import { MapView } from "@/components/rv/map-view";
import { ConfirmSheet } from "@/components/rv/confirm-sheet";

function group(issues: Issue[]) {
  const g: { title: string; items: Issue[] }[] = [];
  const open = issues.filter((i) => !i.announced);
  const done = issues.filter((i) => i.announced);
  if (open.length) g.push({ title: "De verificat și anunțat", items: open });
  if (done.length) g.push({ title: "Anunțate", items: done });
  return g;
}

export function InboxLayout({ acum }: { acum: Acum }) {
  const [sel, setSel] = useState(acum.issues[0]?.id ?? null);
  const issue = acum.issues.find((i) => i.id === sel) ?? acum.issues[0];
  const open = acum.issues.filter((i) => !i.announced).length;
  const [confirm, setConfirm] = useState(new URLSearchParams(window.location.search).get("confirm") === "1");
  return (
    <SidebarProvider>
      <AppSidebar active="acum" counts={{ acum: open, anunta: 1 }} />
      <SidebarInset className="flex h-svh flex-col overflow-hidden">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b px-6">
          <SidebarTrigger className="-ml-2" />
          <Separator orientation="vertical" className="h-5" />
          <h1 className="text-sm font-semibold">Acum</h1>
          <LiveClock acum={acum} className="ml-auto" />
        </header>
        <div className="border-b px-6 py-4">
          <KpiStrip acum={acum} compact />
        </div>
        <div className="grid min-h-0 flex-1 grid-cols-[380px_minmax(0,1fr)]">
          <aside className="flex min-h-0 flex-col overflow-y-auto border-r p-2">
            {group(acum.issues).map((g) => (
              <section key={g.title} className="mb-2">
                <h3 className="px-3 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  {g.title} <span className="tnum">· {g.items.length}</span>
                </h3>
                {g.items.map((i) => (
                  <IssueRow key={i.id} issue={i} selected={i.id === issue?.id} onSelect={() => setSel(i.id)} />
                ))}
              </section>
            ))}
          </aside>
          {issue && (
            <main className="grid min-h-0 grid-cols-[400px_minmax(0,1fr)]">
              <div className="flex min-h-0 flex-col justify-between gap-6 overflow-y-auto border-r p-6">
                <IssueDetail issue={issue} acum={acum} />
                <IssueActions issue={issue} stacked onConfirm={() => setConfirm(true)} />
              </div>
              <div className="relative">
                <MapView
                  network={acum.network}
                  issues={acum.issues}
                  selectedId={issue.id}
                  onSelect={setSel}
                  className="absolute inset-0"
                />
                <div className="pointer-events-none absolute left-4 top-4 rounded-md border bg-background/90 px-2.5 py-1.5 text-xs shadow-sm backdrop-blur">
                  {issue.title} · {issue.statusLabel.toLowerCase()}
                </div>
              </div>
            </main>
          )}
        </div>
      </SidebarInset>
      {issue && <ConfirmSheet issue={issue} acum={acum} open={confirm} onOpenChange={setConfirm} />}
    </SidebarProvider>
  );
}
