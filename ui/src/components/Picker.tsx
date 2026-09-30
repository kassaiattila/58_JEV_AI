// Unified picker (056 U1): replaces every drop-down list in the interface. Always searchable (decision of 2026-09-28,
// even on 2–3-item lists). Keyboard: open with ↓ / Enter / typing, move with ↑ ↓, choose with Enter, close with Esc.
// For a large list (e.g. runs) the local service does the search: then the caller receives the typed text via
// `onSearch` and passes back the already filtered `options`.
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { t, useLocale } from "../i18n";
import { fold } from "../labels";
import { Popover } from "./Popover";

export interface PickerOption { value: string; label: string; detail?: string; group?: string; disabled?: boolean }

interface Props {
  label: string;
  value: string | null;
  options: PickerOption[];
  onChange: (value: string) => void;
  onSearch?: (q: string) => void;
  loading?: boolean;
  placeholder?: string;
  hideLabel?: boolean;
  compact?: boolean;
  disabled?: boolean;
  /** the label of the selected item, when it is not in the (filtered) list at the moment */
  selectedLabel?: string;
  emptyText?: string;
  className?: string;
  more?: number; // how many more matches there are than are shown (with search in the local service)
}

export function Picker(p: Props) {
  useLocale();
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);

  const shown = useMemo(() => {
    if (p.onSearch || !q.trim()) return p.options;
    const needle = fold(q.trim());
    return p.options.filter((o) => fold(`${o.label} ${o.detail ?? ""} ${o.group ?? ""}`).includes(needle));
  }, [p.options, p.onSearch, q]);
  const enabled = shown.filter((o) => !o.disabled);
  const current = p.options.find((o) => o.value === p.value);

  useEffect(() => setActive(Math.max(0, enabled.findIndex((o) => o.value === p.value))), [open, q, shown.length]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!open) return;
    listRef.current?.querySelector<HTMLElement>(`[data-idx="${active}"]`)?.scrollIntoView?.({ block: "nearest" });
  }, [active, open]);

  const openWith = (text = "") => {
    if (p.disabled) return;
    setQ(text);
    p.onSearch?.(text);
    setOpen(true);
  };
  const close = () => {
    setOpen(false);
    setQ("");
  };
  const pick = (o: PickerOption | undefined) => {
    if (!o || o.disabled) return;
    p.onChange(o.value);
    close();
    trigger.current?.focus();
  };
  const onInputKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(enabled.length - 1, a + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); pick(enabled[active]); }
    else if (e.key === "Tab") close();
  };
  const onTriggerKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); openWith(); }
    else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey && e.key !== " ") { e.preventDefault(); openWith(e.key); }
  };

  let lastGroup: string | undefined;
  const listId = `${id}-list`;
  const text = current?.label ?? p.selectedLabel ?? p.placeholder ?? t("Válassz…");
  return (
    <div className={`picker ${p.compact ? "compact" : ""} ${p.className ?? ""}`}>
      <label htmlFor={`${id}-btn`} className={p.hideLabel ? "sr-only" : "picker-label"}>{p.label}</label>
      <button id={`${id}-btn`} ref={trigger} type="button" className="picker-trigger" disabled={p.disabled}
        aria-haspopup="listbox" aria-expanded={open} onClick={() => (open ? close() : openWith())} onKeyDown={onTriggerKey}>
        <span className={current || p.selectedLabel ? "" : "muted"}>{text}</span>
        {current?.detail && !p.compact ? <span className="picker-detail">{current.detail}</span> : null}
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4" /></svg>
      </button>
      <Popover open={open} onClose={close} anchor={trigger} label={p.label} role="presentation" className="picker-pop">
        <input autoFocus className="picker-search" role="combobox" aria-expanded aria-controls={listId} aria-autocomplete="list"
          aria-label={t("{{label}}: keresés", { label: p.label })} placeholder={t("Keresés…")} value={q}
          aria-activedescendant={enabled[active] ? `${id}-o-${shown.indexOf(enabled[active])}` : undefined}
          onChange={(e) => { setQ(e.target.value); p.onSearch?.(e.target.value); }} onKeyDown={onInputKey} />
        <ul ref={listRef} id={listId} role="listbox" aria-label={p.label} className="picker-list">
          {shown.map((o, i) => {
            const idx = enabled.indexOf(o);
            const head = o.group && o.group !== lastGroup ? <li role="presentation" className="picker-group">{o.group}</li> : null;
            lastGroup = o.group;
            return [
              head,
              <li key={o.value} id={`${id}-o-${i}`} role="option" aria-selected={o.value === p.value} aria-disabled={o.disabled || undefined}
                data-idx={idx} className={`picker-opt ${idx === active ? "active" : ""}`}
                onMouseDown={(e) => e.preventDefault()} onMouseEnter={() => idx >= 0 && setActive(idx)} onClick={() => pick(o)}>
                <span>{o.label}</span>{o.detail ? <span className="picker-detail">{o.detail}</span> : null}
              </li>,
            ];
          })}
          {p.loading ? <li role="presentation" className="picker-empty">{t("Keresés…")}</li> : null}
          {!p.loading && shown.length === 0 ? <li role="presentation" className="picker-empty">{p.emptyText ?? t("Nincs találat.")}</li> : null}
          {p.more ? <li role="presentation" className="picker-empty">{t("…és még {{n}} találat — szűkíts a kereséssel.", { n: p.more })}</li> : null}
        </ul>
      </Popover>
    </div>
  );
}
