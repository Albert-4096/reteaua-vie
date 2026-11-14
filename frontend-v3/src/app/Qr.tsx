import { useEffect, useMemo, useRef } from "react";
import qrcode from "qrcode-generator";
import { ExternalLink, X } from "lucide-react";

const QUIET = 4; // white modules around the code, the minimum the QR standard asks for

/** A QR code as one SVG path: black on white, sharp at any size. */
function Code({ url, label }: { url: string; label: string }) {
  const { size, d } = useMemo(() => {
    const qr = qrcode(0, "M");
    qr.addData(url);
    qr.make();
    const n = qr.getModuleCount();
    let path = "";
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (qr.isDark(r, c)) path += `M${c + QUIET} ${r + QUIET}h1v1h-1z`;
    return { size: n + 2 * QUIET, d: path };
  }, [url]);
  return (
    <svg viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label} shapeRendering="crispEdges" className="h-auto w-full rounded-xl">
      <rect width={size} height={size} fill="#fff" />
      <path d={d} fill="#000" />
    </svg>
  );
}

/**
 * The stop poster's QR, large on the screen: nobody prints the poster in a meeting room, so the code is
 * scanned from here. The page it opens is the one riders get at the stop (what does not stop, the nearest
 * served stop, the audio version).
 */
export function QrDialog({ url, stop, onClose }: { url: string | null; stop: string; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (url && !el.open) el.showModal();
    if (!url && el.open) el.close();
  }, [url]);
  return (
    <dialog ref={ref} onClose={onClose} onClick={(e) => { if (e.target === ref.current) onClose(); }}
      className="m-auto w-[min(26rem,calc(100vw-2rem))] rounded-2xl border bg-card p-0 text-foreground shadow-float backdrop:bg-foreground/45">
      {url && (
        <div className="p-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-base font-semibold leading-snug">Afișul stației {stop}</h2>
              <p className="mt-1 text-sm leading-snug text-muted-foreground">Scanați codul cu telefonul: se deschide pagina stației, cu varianta audio.</p>
            </div>
            <button type="button" onClick={onClose} aria-label="Închide"
              className="-mr-2 -mt-1 grid size-8 shrink-0 place-items-center rounded-md text-muted-foreground outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"><X className="size-4" /></button>
          </div>
          <div className="mt-5 border p-2 rounded-2xl bg-white"><Code url={url} label={`Cod QR pentru pagina stației ${stop}`} /></div>
          <a href={`${new URL(url).pathname}${new URL(url).search}&preview=1`} target="_blank" rel="noreferrer"
            className="mt-4 inline-flex items-center gap-1.5 text-sm font-medium text-accent-foreground underline-offset-4 hover:underline">
            Deschide pagina pe acest ecran <ExternalLink className="size-3.5" />
          </a>
        </div>
      )}
    </dialog>
  );
}
