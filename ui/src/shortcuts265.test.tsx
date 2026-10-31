// 265 (code review UI-01): a page's keyboard shortcut runs only for a key nothing else took. On a picker's trigger the
// arrow opened the picker and moved the review page to the next field as well, a typed search letter went to the page,
// and Enter saved the field as checked; the pairing lost its ticked invoices. Artificial elements, no service.
import { render } from "@testing-library/react";
import { expect, it } from "vitest";
import { isShortcutTarget, isTyping } from "./components/shortcuts";

function keyOn(el: HTMLElement, key: string, prevented = false): KeyboardEvent {
  let seen: KeyboardEvent | null = null;
  const on = (e: KeyboardEvent) => { seen = e; };
  window.addEventListener("keydown", on);
  if (prevented) el.addEventListener("keydown", (e) => e.preventDefault(), { once: true });
  el.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
  window.removeEventListener("keydown", on);
  return seen as unknown as KeyboardEvent;
}

it("a key a control handled, or one going into a control that owns the keys, is no page shortcut", () => {
  const { getByTestId } = render(
    <div>
      <button data-testid="picker" aria-haspopup="listbox">Choose</button>
      <button data-testid="plain">Plain</button>
      <a data-testid="link" href="#x">Link</a>
      <input data-testid="text" />
      <input data-testid="box" type="checkbox" />
      <div data-testid="page" tabIndex={0}>page</div>
    </div>,
  );
  expect(isShortcutTarget(keyOn(getByTestId("picker"), "ArrowDown"))).toBe(false);
  expect(isShortcutTarget(keyOn(getByTestId("picker"), "a"))).toBe(false);
  expect(isShortcutTarget(keyOn(getByTestId("text"), "j"))).toBe(false);
  expect(isShortcutTarget(keyOn(getByTestId("page"), "ArrowDown", true))).toBe(false);
  expect(isShortcutTarget(keyOn(getByTestId("plain"), "Enter"))).toBe(false);
  expect(isShortcutTarget(keyOn(getByTestId("link"), " "))).toBe(false);
  expect(isShortcutTarget(keyOn(getByTestId("plain"), "ArrowDown"))).toBe(true);
  expect(isShortcutTarget(keyOn(getByTestId("box"), "j"))).toBe(true);
  expect(isShortcutTarget(keyOn(getByTestId("page"), "Enter"))).toBe(true);
  expect(isTyping(getByTestId("box"))).toBe(false);
});
