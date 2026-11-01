// 265 (code review UI-01): when a page's own keyboard shortcut may run. The review page, the pairing and the proposal
// cards listen on the window; a key a control already handled (a picker's arrow or search letter), or one a control
// gives its own meaning, must not move the page as well.

/** Whether the key goes into a text field (a checkbox, a radio button or a button input takes no letters). */
export const isTyping = (el: EventTarget | null): boolean =>
  el instanceof HTMLElement && ((el instanceof HTMLInputElement && !["checkbox", "radio", "button"].includes(el.type))
    || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable === true);

// a control that owns the arrows, the letters and Enter: a picker's trigger, its search and list, a menu, a drop-down
const OWNS_KEYS = "[aria-haspopup], [role='combobox'], [role='listbox'], [role='menu'], select";
// a control that gives Enter and Space their own meaning (the arrows and letters still move the page)
const CLICKS = "button, a[href], summary";

/** 272 (K3): whether the element is, or lies in, a control that owns the keys (a picker, a menu, a drop-down). */
export const ownsKeys = (el: Element | null): boolean => el !== null && el.closest(OWNS_KEYS) !== null;

/** Whether a page's shortcut may act on this key: nothing handled it before (`defaultPrevented`), it does not go into a
 *  text field or a control that owns the keys, and it is no Enter or Space on a button or a link. */
export function isShortcutTarget(e: KeyboardEvent): boolean {
  if (e.defaultPrevented) return false;
  const el = e.target instanceof HTMLElement ? e.target : null;
  if (el === null) return true;
  if (isTyping(el) || el.closest(OWNS_KEYS)) return false;
  return !((e.key === "Enter" || e.key === " ") && el.closest(CLICKS));
}
