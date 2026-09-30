// 057: language switching (HU / EN, the way the old V4 did it) — the labels update in place, the typed value is kept,
// the choice is remembered, a missing translation shows the Hungarian label, and the placeholder is filled with the
// parameter.
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { LanguageSwitch } from "./components/LanguageSwitch";
import { getLocale, LANGUAGE_STORAGE_KEY, setLanguage, t, useLocale } from "./i18n";
import { MODE, reasonText } from "./labels";

function Draft() {
  useLocale();
  const [value, setValue] = useState("");
  return (
    <label>{t("Számlaszám")}<input value={value} onChange={(e) => setValue(e.target.value)} /></label>
  );
}

afterEach(async () => {
  await act(() => setLanguage("hu"));
  localStorage.removeItem(LANGUAGE_STORAGE_KEY);
});

describe("nyelvváltás", () => {
  it("angolra váltva a felirat helyben frissül, a beírt érték megmarad, a választás tárolódik", async () => {
    render(<><LanguageSwitch /><Draft /></>);
    await userEvent.type(screen.getByLabelText("Számlaszám"), "MINTA-7");
    await userEvent.click(screen.getByRole("button", { name: "EN" }));
    const input = await screen.findByLabelText("Invoice number") as HTMLInputElement;
    expect(input.value).toBe("MINTA-7"); // the working copy was not lost
    expect(screen.getByRole("button", { name: "EN" }).getAttribute("aria-pressed")).toBe("true");
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("en");
    expect(document.documentElement.lang).toBe("en");
    expect(getLocale()).toBe("en-GB");
  });

  it("címkeszótár, paraméteres mondat, és hiányzó kulcsnál a magyar forrás", async () => {
    await act(() => setLanguage("en"));
    expect(MODE.apply).toBe("Live");
    expect(reasonText("pick:none:invoice_number")).toBe("No value: Invoice number");
    expect(t("Ez a mondat nincs a szótárban")).toBe("Ez a mondat nincs a szótárban");
    await act(() => setLanguage("hu"));
    expect(MODE.apply).toBe("Éles");
  });
});
