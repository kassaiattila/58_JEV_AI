// 151 (the owner's decision of 2026-10-12): an older live run that a later live run repeated on the same documents can
// be superseded on its page. The offer says how many open to-dos close and warns when human work stays behind; the
// button asks for a second click. Artificial data, no service.
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { setLanguage } from "./i18n";
import { SupersedeOffer } from "./views/Runs";

afterEach(async () => { vi.restoreAllMocks(); await setLanguage("hu"); });

const OFFER = { by: "run-000000000002", open_reasons: 142, resolved_reasons: 0, corrected_items: 0 };

describe("151 superseding an older live run", () => {
  it("names the later run and the to-dos that close, and confirms with a second click", () => {
    const onConfirm = vi.fn();
    render(<SupersedeOffer offer={OFFER} busy={false} onConfirm={onConfirm} />);
    expect(screen.getByRole("link", { name: "Az újabb futás" }).getAttribute("href")).toBe("#/runs/run-000000000002");
    expect(screen.getByText(/142 nyitott teendője lezárul/)).toBeTruthy();
    expect(screen.queryByText(/kézzel javítottak/)).toBeNull(); // no human work: no warning
    fireEvent.click(screen.getByRole("button", { name: "Leváltás" }));
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Biztosan? Kattints újra" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("warns when to-dos were closed or documents corrected on the run", async () => {
    render(<SupersedeOffer offer={{ ...OFFER, resolved_reasons: 25, corrected_items: 1 }} busy={false} onConfirm={() => {}} />);
    expect(screen.getByText(/már 25 teendőt lezártak és 1 iratot kézzel javítottak/)).toBeTruthy();
  });

  it("reads in English too", async () => {
    await setLanguage("en");
    render(<SupersedeOffer offer={OFFER} busy={false} onConfirm={() => {}} />);
    expect(screen.getByRole("button", { name: "Supersede" })).toBeTruthy();
    expect(screen.getByText(/closes its 142 open to-dos/)).toBeTruthy();
  });
});
