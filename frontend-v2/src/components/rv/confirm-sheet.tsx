// The human step: a dispatcher confirms before anything reaches riders (TriageInput, CONTRACT v2.24).
// Fast by design: one choice, a reason that defaults to "necunoscut", one button.
import { useState } from "react";
import { Check, Smartphone } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import type { Acum, Issue } from "@/lib/acum";
import { LineBadge, StatusMark } from "./status";

const CHOICES = [
  { id: "confirmat", label: "Da, nu circulă niciun vehicul", hint: "Călătorii văd starea în CityApp." },
  { id: "respins", label: "Nu, vehiculul circulă", hint: "Ex.: GPS oprit. Nu pleacă nimic spre călători." },
  { id: "nu_stiu", label: "Nu știu încă", hint: "Rămâne în listă. Nu pleacă nimic." },
] as const;

const REASONS = [
  { id: "", label: "Motiv necunoscut" },
  { id: "dispozitiv_bord", label: "Dispozitiv de bord defect" },
  { id: "linie_neoperata", label: "Linie neoperată" },
  { id: "trafic_lucrari_vreme", label: "Trafic, lucrări sau vreme" },
  { id: "gol_date", label: "Gol în date" },
];

export function ConfirmSheet({ issue, acum, open, onOpenChange }: { issue: Issue; acum: Acum; open: boolean; onOpenChange: (o: boolean) => void }) {
  const [choice, setChoice] = useState<(typeof CHOICES)[number]["id"]>("confirmat");
  const [reason, setReason] = useState("");
  const route = issue.lines[0];
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex w-[560px] flex-col gap-0 p-0 sm:max-w-[560px]">
        <SheetHeader className="border-b p-6">
          <SheetTitle className="flex items-center gap-2 text-lg">
            {route && <LineBadge route={route} />} Anunță călătorii
          </SheetTitle>
          <SheetDescription>
            {issue.title}: {issue.planned.value} {issue.planned.label}, {issue.actual.value} {issue.actual.label} ({acum.windowLabel}). Confirmă ce știe dispeceratul.
          </SheetDescription>
        </SheetHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto p-6">
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-2 text-sm font-medium">Linia circulă fără vehicule?</legend>
            {CHOICES.map((c) => (
              <label
                key={c.id}
                className={cn(
                  "flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors hover:bg-accent",
                  choice === c.id && "border-primary bg-accent",
                )}
              >
                <input type="radio" name="choice" value={c.id} checked={choice === c.id} onChange={() => setChoice(c.id)} className="mt-1 accent-primary" />
                <span>
                  <span className="block text-sm font-medium">{c.label}</span>
                  <span className="block text-xs text-muted-foreground">{c.hint}</span>
                </span>
              </label>
            ))}
          </fieldset>

          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium">Motiv</span>
              <select value={reason} onChange={(e) => setReason(e.target.value)} className="h-9 rounded-md border bg-background px-2 text-sm">
                {REASONS.map((r) => (
                  <option key={r.id} value={r.id}>{r.label}</option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1.5 text-sm">
              <span className="font-medium">Cine confirmă</span>
              <input defaultValue="dispecer STPT" className="h-9 rounded-md border bg-background px-2 text-sm" aria-describedby="who-hint" />
              <span id="who-hint" className="text-xs text-muted-foreground">Un rol, niciodată un nume.</span>
            </label>
          </div>

          <div>
            <div className="mb-2 flex items-center gap-2 text-sm font-medium">
              <Smartphone className="size-4" /> Ce văd călătorii
              <span className="ml-auto rounded-full bg-secondary px-2 py-0.5 text-[11px] font-normal text-muted-foreground">machetă CityApp, din API</span>
            </div>
            <div className={cn("rounded-2xl border bg-muted/40 p-4 transition-opacity", choice !== "confirmat" && "opacity-40")}>
              <div className="rounded-xl bg-card p-4 shadow-sm">
                <div className="flex items-center gap-3">
                  {route && <LineBadge route={route} size="lg" />}
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold">{issue.subtitle}</div>
                    <div className="mt-0.5 flex items-center gap-1.5 text-xs font-medium text-st-none">
                      <StatusMark level={3} className="size-2.5" /> Fără vehicul pe traseu în datele live
                    </div>
                  </div>
                </div>
                <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                  Ora din orar poate să nu fie reală. Verificați o altă linie. Confirmat de dispeceratul STPT
                  {reason ? `: ${REASONS.find((r) => r.id === reason)?.label.toLowerCase()}` : ""}.
                </p>
              </div>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              {choice === "confirmat"
                ? "Pleacă doar în fluxul CityApp. Nu marcăm cursele ca anulate în GTFS-RT."
                : "Nu pleacă nimic spre călători. Decizia intră în jurnalul lunar pentru SMTT."}
            </p>
          </div>
        </div>

        <SheetFooter className="flex-row justify-end gap-2 border-t p-4">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Renunță</Button>
          <Button size="lg">
            <Check /> {choice === "confirmat" ? "Confirmă și publică" : "Salvează decizia"}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
