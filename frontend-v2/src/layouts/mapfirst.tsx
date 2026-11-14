// Varianta 3: the map fills the screen; navigation on top; issues and the selected issue float over it.
import { useState } from "react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { Acum } from "@/lib/acum";
import { Logo } from "@/components/rv/app-sidebar";
import { IssueActions, IssueDetail, IssueRow, KpiStrip, LiveClock, NAV } from "@/components/rv/parts";
import { MapView } from "@/components/rv/map-view";
import { ConfirmSheet } from "@/components/rv/confirm-sheet";

export function MapFirstLayout({ acum }: { acum: Acum }) {
  const [sel, setSel] = useState(acum.issues[0]?.id ?? null);
  const issue = acum.issues.find((i) => i.id === sel) ?? acum.issues[0];
  const open = acum.issues.filter((i) => !i.announced).length;
  const [confirm, setConfirm] = useState(new URLSearchParams(window.location.search).get("confirm") === "1");
  return (
    <div className="flex h-svh flex-col">
      <header className="z-10 flex h-14 shrink-0 items-center gap-8 border-b bg-background px-5">
        <Logo />
        <nav className="flex h-full items-center gap-1">
          {NAV.map((n) => (
            <a
              key={n.id}
              href="#"
              className={cn(
                "relative flex h-full items-center gap-2 px-3 text-sm text-muted-foreground hover:text-foreground",
                n.id === "acum" && "font-medium text-foreground after:absolute after:inset-x-2 after:bottom-0 after:h-0.5 after:bg-foreground",
              )}
            >
              <n.icon className="size-4" />
              {n.label}
              {n.id === "acum" && open > 0 && (
                <span className="tnum rounded-full bg-st-none px-1.5 text-[11px] font-semibold text-white">{open}</span>
              )}
            </a>
          ))}
        </nav>
        <LiveClock acum={acum} className="ml-auto" />
      </header>
      <div className="relative min-h-0 flex-1">
        <MapView
          network={acum.network}
          issues={acum.issues}
          selectedId={issue?.id ?? null}
          onSelect={setSel}
          padding={{ top: 80, right: 440, bottom: 80, left: 440 }}
          className="absolute inset-0"
        />
        <Card className="absolute left-4 top-4 w-[400px] gap-0 p-0 shadow-lg">
          <div className="border-b px-4 py-3">
            <div className="text-sm font-semibold">Ce nu merge acum</div>
            <div className="text-xs text-muted-foreground">{acum.issues.length} probleme · {open} neanunțate</div>
          </div>
          <div className="flex flex-col gap-0.5 p-1.5">
            {acum.issues.map((i) => (
              <IssueRow key={i.id} issue={i} selected={i.id === issue?.id} onSelect={() => setSel(i.id)} />
            ))}
          </div>
        </Card>
        {issue && (
          <Card className="absolute bottom-4 right-4 top-4 flex w-[400px] flex-col justify-between gap-6 overflow-y-auto p-5 shadow-lg">
            <IssueDetail issue={issue} acum={acum} />
            <IssueActions issue={issue} stacked onConfirm={() => setConfirm(true)} />
          </Card>
        )}
        <Card className="absolute bottom-4 left-4 w-[400px] p-4 shadow-lg">
          <KpiStrip acum={acum} compact cols={2} />
        </Card>
      </div>
      {issue && <ConfirmSheet issue={issue} acum={acum} open={confirm} onOpenChange={setConfirm} />}
    </div>
  );
}
