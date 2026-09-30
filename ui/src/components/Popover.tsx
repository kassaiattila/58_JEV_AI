// Kis felugró réteg egy gomb alatt (056 U1): a választó, az oszlopszűrő, az oszlopválasztó és a letöltés-panel közös
// alapja. A lap legfelső rétegébe kerül (a görgetett táblázat nem vágja le), a nyitó gombhoz igazodik, görgetéskor és
// átméretezéskor követi. Kívül kattintásra és Esc-re bezárul, a fókusz ilyenkor visszakerül a nyitó gombra.
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";

interface Props {
  open: boolean;
  onClose: () => void;
  anchor: RefObject<HTMLElement | null>;
  children: ReactNode;
  label: string;
  className?: string;
  role?: "dialog" | "presentation";
  align?: "left" | "right";
}

const GAP = 4;
const MARGIN = 8;

export function Popover({ open, onClose, anchor, children, label, className, role = "dialog", align = "left" }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number; maxHeight: number } | null>(null);

  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const a = anchor.current?.getBoundingClientRect();
      const el = ref.current;
      if (!a || !el) return;
      const w = el.offsetWidth;
      const h = el.offsetHeight;
      let left = align === "right" ? a.right - w : a.left;
      left = Math.max(MARGIN, Math.min(left, window.innerWidth - w - MARGIN));
      const below = window.innerHeight - a.bottom - GAP - MARGIN;
      const above = a.top - GAP - MARGIN;
      const flip = h > below && above > below; // alul nincs hely, felül több van: felfelé nyílik
      const maxHeight = Math.max(160, flip ? above : below);
      const top = flip ? Math.max(MARGIN, a.top - GAP - Math.min(h, maxHeight)) : a.bottom + GAP;
      setPos({ top, left, maxHeight });
    };
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open, anchor, align]);

  useEffect(() => {
    if (!open) {
      setPos(null);
      return;
    }
    const down = (e: MouseEvent) => {
      const t = e.target as Node;
      if (ref.current?.contains(t) || anchor.current?.contains(t)) return;
      onClose();
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        anchor.current?.focus();
      }
    };
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", down);
      document.removeEventListener("keydown", key);
    };
  }, [open, onClose, anchor]);

  if (!open) return null;
  return createPortal(
    <div ref={ref} className={`popover ${className ?? ""}`} role={role} aria-label={role === "dialog" ? label : undefined}
      style={pos ? { top: pos.top, left: pos.left, maxHeight: pos.maxHeight } : { top: 0, left: 0, visibility: "hidden" }}>
      {children}
    </div>,
    document.body,
  );
}
