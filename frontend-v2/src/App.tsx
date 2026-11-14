import { TooltipProvider } from "@/components/ui/tooltip";
import { Skeleton } from "@/components/ui/skeleton";
import { useAcum } from "@/lib/acum";
import { SplitLayout } from "@/layouts/split";
import { InboxLayout } from "@/layouts/inbox";
import { MapFirstLayout } from "@/layouts/mapfirst";

export default function App() {
  const layout = new URLSearchParams(window.location.search).get("layout") ?? "2";
  const { acum, error } = useAcum();
  if (error) return <div className="p-8 text-sm text-destructive">Datele nu s-au încărcat: {error}</div>;
  if (!acum)
    return (
      <div className="grid h-svh grid-cols-[256px_1fr]">
        <div className="border-r bg-sidebar" />
        <div className="flex flex-col gap-4 p-6">
          <Skeleton className="h-8 w-60" />
          <div className="grid grid-cols-4 gap-3">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24" />)}</div>
          <Skeleton className="flex-1" />
        </div>
      </div>
    );
  return (
    <TooltipProvider>
      {layout === "1" ? <SplitLayout acum={acum} /> : layout === "3" ? <MapFirstLayout acum={acum} /> : <InboxLayout acum={acum} />}
    </TooltipProvider>
  );
}
