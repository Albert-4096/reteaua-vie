// The QR moment (D-028): nobody prints the poster, so its QR is drawn on screen, large enough to
// scan from a few metres, and the phone page can be opened in a phone-size frame when nobody scans.
import { useEffect, useMemo, useRef } from "react";
import qrcode from "../../vendor/qrcode/qrcode.mjs";
import { tr } from "../../lib/format";
import { S } from "./strings";
import "./qrMoment.css";

const QUIET = 4; // modules of white around the code, the minimum the QR standard asks for

/** The same URL the poster PDF encodes (the alert's `url`), as one SVG path. Dark on white in both themes. */
export function ScreenQr({ url }: { url: string }) {
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
    <figure className="qrm">
      <svg className="qrm-code" viewBox={`0 0 ${size} ${size}`} role="img" aria-label={tr(S.qrAlt)} shapeRendering="crispEdges">
        <rect width={size} height={size} fill="#fff" />
        <path d={d} fill="#000" />
      </svg>
      <figcaption>{tr(S.qrHint)}</figcaption>
    </figure>
  );
}

/** The phone page in a phone-size frame. `preview=1` keeps it out of the poster scan counter (R7). */
export function PhoneFrame({ href, open, onClose }: { href: string; open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);
  const src = href + (href.includes("?") ? "&" : "?") + "preview=1";
  return (
    <dialog ref={ref} className="qrm-phone" aria-label={tr(S.qrPhoneTitle)} onClose={onClose}>
      <div className="qrm-phone-bar">
        <span>{tr(S.qrPhoneTitle)}</span>
        <button type="button" className="btn" onClick={onClose}>
          {tr(S.qrPhoneClose)}
        </button>
      </div>
      {open && <iframe title={tr(S.qrPhoneTitle)} src={src} />}
    </dialog>
  );
}
