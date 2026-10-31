// 263 (plan E, E1; the owner's decision of 2026-10-30: "the left panel can be hidden and optionally pinned, and while it
// shows, its width can be dragged"): the left panel of a page with a table of contents or views (Settings; the Cases'
// views later). Pinned, it takes its place beside the page; hidden, a narrow strip with one button stays, which opens it
// over the page until a node is chosen (an address change), Escape or a click beside it. While it shows, its right edge
// is dragged (or moved with ← / →) to make it narrower or wider. Whether it is pinned and its width are kept per
// browser, for each panel.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useFitToScreen, useHash } from "../hooks";
import { t, useLocale } from "../i18n";
import { Icon } from "./Icon";

interface Prefs { pinned: boolean; width: number }
const MIN = 180;
const MAX = 480;
// 264 (G2): narrower at first (until then 264): the longest section name fits, the page gets the rest
const DEFAULT: Prefs = { pinned: true, width: 224 };
const clamp = (w: number) => Math.min(MAX, Math.max(MIN, Math.round(w)));
const key = (id: string) => `jav.panel.${id}`;

function load(id: string): Prefs {
  try {
    const saved = JSON.parse(localStorage.getItem(key(id)) ?? "{}") as Partial<Prefs>;
    return { pinned: saved.pinned ?? DEFAULT.pinned, width: clamp(saved.width ?? DEFAULT.width) };
  } catch {
    return DEFAULT;
  }
}
function save(id: string, prefs: Prefs) {
  try { localStorage.setItem(key(id), JSON.stringify(prefs)); } catch { /* private window: for the session only */ }
}

export function SidePanel({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  useLocale();
  const [prefs, setPrefs] = useState<Prefs>(() => load(id));
  const [open, setOpen] = useState(false); // shown over the page while it is not pinned
  const fit = useFitToScreen<HTMLDivElement>("--panel-offset");
  const box = useRef<HTMLElement>(null);
  const hash = useHash();
  useEffect(() => setOpen(false), [hash]); // a node chosen: the page shows, the panel steps aside
  const update = (next: Partial<Prefs>) => setPrefs((was) => {
    const merged = { ...was, ...next };
    save(id, merged);
    return merged;
  });
  useEffect(() => { // over the page: Escape or a click beside it closes it
    if (prefs.pinned || !open) return;
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    const click = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    window.addEventListener("keydown", key);
    window.addEventListener("pointerdown", click);
    return () => { window.removeEventListener("keydown", key); window.removeEventListener("pointerdown", click); };
  }, [prefs.pinned, open]);

  function onPointerDown(e: React.PointerEvent) {
    e.preventDefault();
    const left = box.current?.getBoundingClientRect().left ?? 0;
    let last = prefs.width;
    const move = (ev: PointerEvent) => {
      last = clamp(ev.clientX - left);
      setPrefs((was) => ({ ...was, width: last }));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.classList.remove("dragging");
      update({ width: last });
    };
    document.body.classList.add("dragging");
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  const shown = prefs.pinned || open;
  return (
    <div ref={fit} className={`side-slot${prefs.pinned ? " pinned" : ""}`} style={prefs.pinned ? { width: prefs.width } : undefined}>
      {!prefs.pinned ? (
        <button type="button" className="side-reveal" aria-expanded={open} aria-controls={`side-${id}`} title={label}
          onClick={() => setOpen(!open)}>
          <Icon name="panel" /><span className="sr-only">{label}</span>
        </button>
      ) : null}
      {shown ? (
        <aside ref={box} id={`side-${id}`} className={`side-panel${prefs.pinned ? "" : " floating"}`} aria-label={label} style={{ width: prefs.width }}>
          <div className="side-head">
            <span className="side-title">{label}</span>
            {prefs.pinned ? (
              <button type="button" className="quiet small-btn" onClick={() => update({ pinned: false })}>{t("Hide")}</button>
            ) : (
              <>
                <button type="button" className="quiet small-btn" onClick={() => { update({ pinned: true }); setOpen(false); }}>{t("Pin")}</button>
                <button type="button" className="quiet small-btn" aria-label={t("Close")} onClick={() => setOpen(false)}><Icon name="close" /></button>
              </>
            )}
          </div>
          <div className="side-body">{children}</div>
          <div className="side-handle" role="separator" aria-orientation="vertical" aria-label={t("Width of the panel")}
            aria-valuenow={prefs.width} aria-valuemin={MIN} aria-valuemax={MAX} tabIndex={0} onPointerDown={onPointerDown}
            onKeyDown={(e) => {
              if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
                e.preventDefault();
                update({ width: clamp(prefs.width + (e.key === "ArrowLeft" ? -16 : 16)) });
              }
            }} />
        </aside>
      ) : null}
    </div>
  );
}
