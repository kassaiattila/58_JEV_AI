// 057: nyelvváltás (HU / EN, a régi V4 módján) — a feliratok helyben frissülnek, a beírt érték megmarad, a választás
// megmarad, hiányzó fordításnál a magyar felirat látszik, a helyőrző a paraméterrel töltődik.
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
    expect(input.value).toBe("MINTA-7"); // a munkapéldány nem veszett el
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
