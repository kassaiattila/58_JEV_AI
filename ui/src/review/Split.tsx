// Húzható elválasztó a kép és a mezők között (a V4 ResizableSplit mintája): 35–75 %, az arány megmarad a böngészőben.
// Billentyűzettel is állítható (az elválasztón ←/→). 048: a tételes lista fülén külön arány él (alapból szélesebb panel),
// hogy a mezők megszokott aránya ne változzon.
import { useRef, useState, type ReactNode } from "react";
import { t, useLocale } from "../i18n";

const clamp = (v: number) => Math.min(75, Math.max(35, v));
const VARIANTS = { fields: { key: "jav.review.split", ratio: 60 }, list: { key: "jav.review.split.list", ratio: 40 } };

function initial(variant: keyof typeof VARIANTS): number {
  const { key, ratio } = VARIANTS[variant];
  try {
    const v = Number(localStorage.getItem(key));
    return Number.isFinite(v) && v > 0 ? clamp(v) : ratio;
  } catch {
    return ratio;
  }
}

export function Split({ left, right, variant = "fields" }: { left: ReactNode; right: ReactNode; variant?: keyof typeof VARIANTS }) {
  useLocale();
  const [ratios, setRatios] = useState(() => ({ fields: initial("fields"), list: initial("list") }));
  const ratio = ratios[variant];
  const setRatio = (v: number) => setRatios((r) => ({ ...r, [variant]: v }));
  const KEY = VARIANTS[variant].key;
  const box = useRef<HTMLDivElement | null>(null);
  const save = (v: number) => {
    try { localStorage.setItem(KEY, String(v)); } catch { /* privát ablakban nem tárolható; csak a munkamenetig él */ }
  };

  function onPointerDown(e: React.PointerEvent) {
    e.preventDefault();
    const el = box.current!;
    let last = ratio;
    const move = (ev: PointerEvent) => {
      const r = el.getBoundingClientRect();
      last = clamp(((ev.clientX - r.left) / r.width) * 100);
      setRatio(last);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.classList.remove("dragging");
      save(last);
    };
    document.body.classList.add("dragging");
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  return (
    <div ref={box} className="split" style={{ gridTemplateColumns: `minmax(0, ${ratio}fr) 10px minmax(0, ${100 - ratio}fr)` }}>
      <div className="split-pane">{left}</div>
      <div className="split-handle" role="separator" aria-orientation="vertical" aria-label={t("A kép és a mezők aránya")}
        aria-valuenow={Math.round(ratio)} aria-valuemin={35} aria-valuemax={75} tabIndex={0} onPointerDown={onPointerDown}
        onKeyDown={(e) => {
          if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
            const v = clamp(ratio + (e.key === "ArrowLeft" ? -2 : 2));
            setRatio(v);
            save(v);
          }
        }} />
      <div className="split-pane">{right}</div>
    </div>
  );
}
