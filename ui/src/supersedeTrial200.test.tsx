// 200 (the owner's decision of 2026-10-22, Q-visszavont-teendok): an older trial run with open to-dos that a later run
// repeated on the same documents can be superseded too, on its page and in the package's processing section. The wording
// says "run", not "live run", and does not speak of an approval a trial never has. Artificial data, no service.
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { setLanguage } from "./i18n";
import { OlderRunsOffer } from "./views/ProcessStage";
import { SupersedeOffer } from "./views/Runs";

afterEach(async () => { vi.restoreAllMocks(); await setLanguage("hu"); });

const OFFER = { by: "run-000000000002", open_reasons: 10, resolved_reasons: 0, corrected_items: 0 };
const LIVE = { run_id: "run-000000000001", mode: "apply" as const, created_at: "2026-10-01T07:12:06+00:00", ...OFFER };
const TRIAL = { run_id: "run-000000000003", mode: "shadow" as const, created_at: "2026-10-22T08:39:00+00:00", ...OFFER };

describe("200 superseding an older trial run", () => {
  it("on the run's page, without an approval and without 'live'", () => {
    render(<SupersedeOffer offer={OFFER} trial busy={false} onConfirm={() => {}} />);
    expect(screen.getByText(/Egy újabb futás ugyanezeket az iratokat újra feldolgozta/)).toBeTruthy();
    expect(screen.getByText(/ez a próbafutás leállítottként megmarad, 10 nyitott teendője lezárul/)).toBeTruthy();
    expect(screen.queryByText(/éles/)).toBeNull();
    expect(screen.queryByText(/jóvá/)).toBeNull();
    expect(screen.getByRole("button", { name: "Leváltás" })).toBeTruthy();
  });

  it("in the package's list, each run named by its kind", () => {
    render(<OlderRunsOffer runs={[LIVE, TRIAL]} busy={false} onSupersede={() => {}} />);
    expect(screen.getByText(/2 régebbi futást egy újabb futás megismételt/)).toBeTruthy();
    expect(screen.getByRole("link", { name: /Éles futás/ }).getAttribute("href")).toBe("#/runs/run-000000000001");
    expect(screen.getByRole("link", { name: /Próbafutás/ }).getAttribute("href")).toBe("#/runs/run-000000000003");
  });

  it("keeps the live runs' wording when the list has live runs only", () => {
    render(<OlderRunsOffer runs={[LIVE]} busy={false} onSupersede={() => {}} />);
    expect(screen.getByText(/1 régebbi éles futást egy újabb éles futás megismételt/)).toBeTruthy();
  });

  it("reads in English too", async () => {
    await setLanguage("en");
    render(<SupersedeOffer offer={OFFER} trial busy={false} onConfirm={() => {}} />);
    expect(screen.getByText(/Superseding keeps this trial run as a stopped run and closes its 10 open to-dos/)).toBeTruthy();
    render(<OlderRunsOffer runs={[TRIAL]} busy={false} onSupersede={() => {}} />);
    expect(screen.getByRole("link", { name: /Trial run/ })).toBeTruthy();
  });
});
