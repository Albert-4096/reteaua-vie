// Varianta 1: sidebar, KPI row, then map and issue list side by side.
import { useState } from "react";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import type { Acum } from "@/lib/acum";
import { AppSidebar } from "@/components/rv/app-sidebar";
import { IssueActions, IssueDetail, IssueRow, KpiStrip, LiveClock } from "@/components/rv/parts";
import { MapView } from "@/components/rv/map-view";
import { ConfirmSheet } from "@/components/rv/confirm-sheet";

export function SplitLayout({ acum }: { acum: Acum }) {
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
          <span className="text-sm text-muted-foreground">Ce nu merge pe rețea în acest moment</span>
          <LiveClock acum={acum} className="ml-auto" />
        </header>
        <div className="flex min-h-0 flex-1 flex-col gap-4 p-6">
          <KpiStrip acum={acum} />
          <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_400px] gap-4">
            <Card className="relative overflow-hidden p-0 shadow-none">
              <MapView network={acum.network} issues={acum.issues} selectedId={issue?.id ?? null} onSelect={setSel} className="absolute inset-0" />
            </Card>
            <Card className="flex min-h-0 flex-col gap-0 overflow-hidden p-0 shadow-none">
              <div className="flex items-center justify-between border-b px-4 py-3">
                <span className="text-sm font-semibold">Probleme</span>
                <span className="text-xs text-muted-foreground tnum">{acum.issues.length} · {open} neanunțate</span>
              </div>
              <div className="flex flex-col gap-0.5 p-1.5">
                {acum.issues.map((i) => (
                  <IssueRow key={i.id} issue={i} selected={i.id === issue?.id} onSelect={() => setSel(i.id)} />
                ))}
              </div>
              {issue && (
                <div className="mt-auto flex min-h-0 flex-col gap-4 overflow-y-auto border-t p-4">
                  <IssueDetail issue={issue} acum={acum} hideHeader className="gap-4" />
                  <IssueActions issue={issue} stacked onConfirm={() => setConfirm(true)} />
                </div>
              )}
            </Card>
          </div>
        </div>
      </SidebarInset>
      {issue && <ConfirmSheet issue={issue} acum={acum} open={confirm} onOpenChange={setConfirm} />}
    </SidebarProvider>
  );
}
