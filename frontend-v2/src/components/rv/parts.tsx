import { Activity, Construction, FileText, Megaphone, ArrowRight, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { Acum, Issue } from "@/lib/acum";
import { dayLabel, hhmm } from "@/lib/api";
import { Announced, LineBadge, Status, StatusMark } from "./status";
import { PlannedVsActual } from "./compare";

export const NAV = [
  { id: "acum", label: "Acum", hint: "Ce nu merge acum", icon: Activity },
  { id: "planifica", label: "Planifică", hint: "Ce se întâmplă dacă închidem", icon: Construction },
  { id: "anunta", label: "Anunță", hint: "Au aflat oamenii?", icon: Megaphone },
  { id: "rapoarte", label: "Rapoarte", hint: "Ce trimitem lunar", icon: FileText },
] as const;

export function LiveClock({ acum, className }: { acum: Acum; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2 text-xs text-muted-foreground", className)}>
      <span className="relative flex size-2">
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-500/50 motion-reduce:hidden" />
        <span className="relative inline-flex size-2 rounded-full bg-emerald-500" />
      </span>
      <span className="tnum">Date live · {dayLabel(acum.at)}, {hhmm(acum.at)}</span>
    </span>
  );
}

export function KpiStrip({ acum, compact, cols = 4 }: { acum: Acum; compact?: boolean; cols?: 2 | 4 }) {
  return (
    <div className={cn("grid", cols === 4 ? "grid-cols-4" : "grid-cols-2 gap-y-4", compact ? (cols === 4 ? "divide-x" : "") : "gap-3")}>
      {acum.kpis.map((k) => {
        const body = (
          <>
            <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              {k.level > 0 && <StatusMark level={k.level} className="size-2.5" />}
              {k.label}
            </div>
            <div className={cn("tnum font-semibold tracking-tight", compact ? "mt-1 text-xl" : "mt-2 text-3xl")}>{k.value}</div>
            <div className="mt-0.5 text-xs text-muted-foreground">{k.hint}</div>
          </>
        );
        return compact ? (
          <div key={k.id} className={cols === 4 ? "px-4 first:pl-0" : "pr-3"}>{body}</div>
        ) : (
          <Card key={k.id} className="gap-0 px-5 py-4 shadow-none">{body}</Card>
        );
      })}
    </div>
  );
}

export function IssueRow({ issue, selected, onSelect }: { issue: Issue; selected?: boolean; onSelect?: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected ? "true" : undefined}
      className={cn(
        "group grid w-full grid-cols-[auto_1fr_auto] items-start gap-x-3 gap-y-1 rounded-lg px-3 py-3 text-left transition-colors",
        "hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring",
        selected && "bg-accent",
      )}
    >
      <StatusMark level={issue.level} className="mt-1" />
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-semibold">{issue.title}</span>
          {issue.kind === "line" && issue.lines[0] && <LineBadge route={issue.lines[0]} size="sm" />}
        </div>
        <div className="truncate text-xs text-muted-foreground">{issue.subtitle}</div>
      </div>
      <div className="text-right">
        <div className="tnum text-sm font-semibold">
          <span className="text-muted-foreground line-through decoration-muted-foreground/60">{issue.planned.value}</span>
          <span className="mx-1 text-muted-foreground/60">→</span>
          <span className={issue.level === 3 ? "text-st-none" : "text-st-reduced-ink"}>{issue.actual.value}</span>
        </div>
      </div>
      <div />
      <div className="col-span-2 flex items-center gap-2">
        <Status level={issue.level} label={issue.statusLabel} />
        <Announced yes={issue.announced} note={issue.announcedNote} />
      </div>
    </button>
  );
}

export function IssueDetail({ issue, acum, className, hideHeader }: { issue: Issue; acum: Acum; className?: string; hideHeader?: boolean }) {
  return (
    <div className={cn("flex flex-col gap-5", className)}>
      {!hideHeader && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <Status level={issue.level} label={issue.statusLabel} />
            <Announced yes={issue.announced} note={issue.announcedNote} />
          </div>
          <div className="flex items-start gap-3">
            {issue.kind === "line" && issue.lines[0] && <LineBadge route={issue.lines[0]} size="lg" />}
            <div className="min-w-0">
              <h2 className="text-xl font-semibold leading-tight tracking-tight">{issue.title}</h2>
              <p className="text-sm text-muted-foreground">{issue.subtitle}</p>
            </div>
          </div>
          {issue.kind === "works" && (
            <div className="flex flex-wrap gap-1">
              {issue.lines.map((l) => (
                <LineBadge key={l.id} route={l} size="sm" />
              ))}
            </div>
          )}
        </div>
      )}
      <div>
        <PlannedVsActual issue={issue} size="lg" />
        <p className="mt-2 text-xs text-muted-foreground">
          {issue.kind === "line" ? `Ultima oră, ${acum.windowLabel}` : `Azi, ${dayLabel(acum.at)}`}
        </p>
      </div>
      <dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-6 gap-y-2 border-t pt-4 text-sm">
        {issue.facts.map((f) => (
          <div key={f.label} className="contents">
            <dt className="text-muted-foreground">{f.label}</dt>
            <dd className="tnum text-right font-medium">{f.value}</dd>
          </div>
        ))}
      </dl>
      <p className="flex gap-1.5 text-xs leading-relaxed text-muted-foreground">
        <Info className="mt-0.5 size-3.5 shrink-0" />
        {issue.kind === "line"
          ? "Niciun vehicul al liniei nu a apărut în datele live ale Primăriei. Nu știm încă dacă e o cursă nefăcută sau un GPS oprit: dispeceratul confirmă."
          : issue.source}
      </p>
    </div>
  );
}

export function IssueActions({ issue, stacked, onConfirm }: { issue: Issue; stacked?: boolean; onConfirm?: () => void }) {
  if (issue.kind === "works")
    return (
      <div className={cn("flex gap-2", stacked && "flex-col")}>
        <Button size="lg" variant="outline" className={stacked ? "" : "flex-1"}>Vezi stațiile închise</Button>
        <Button size="lg" variant="secondary" className={stacked ? "" : "flex-1"}>Ce văd călătorii</Button>
      </div>
    );
  return (
    <div className={cn("flex gap-2", stacked && "flex-col")}>
      <Button size="lg" className={stacked ? "" : "flex-1"} onClick={onConfirm}>
        Confirmă și anunță călătorii <ArrowRight />
      </Button>
      <Button size="lg" variant="outline">Vehiculul circulă</Button>
    </div>
  );
}
