// 152 (the owner's request of 2026-10-12): the package's processing section lists the older live runs a later live run
// repeated, each with a link to its page and a "Supersede" button that asks for a second click; human work left on a run
// is named before the click. Artificial data, no service.
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { setLanguage } from "./i18n";
import { OlderRunsOffer } from "./views/ProcessStage";
import { confirmAction } from "./confirm.testutil";

afterEach(async () => { vi.restoreAllMocks(); await setLanguage("hu"); });

const RUNS = [
  { run_id: "run-000000000001", created_at: "2026-10-01T07:12:06+00:00", by: "run-000000000003", open_reasons: 142, resolved_reasons: 0, corrected_items: 1 },
  { run_id: "run-000000000002", created_at: "2026-10-01T09:18:44+00:00", by: "run-000000000003", open_reasons: 142, resolved_reasons: 0, corrected_items: 0 },
];

describe("152 the package offers its older live runs for superseding", () => {
  it("lists each run with a link, its open to-dos and a confirmed supersede", () => {
    const onSupersede = vi.fn();
    render(<OlderRunsOffer runs={RUNS} busy={false} onSupersede={onSupersede} />);
    expect(screen.getByText(/2 régebbi éles futást egy újabb éles futás megismételt/)).toBeTruthy();
    expect(screen.getByText(/284 nyitott teendőjüket/)).toBeTruthy();
    const links = screen.getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["#/runs/run-000000000001", "#/runs/run-000000000002"]);
    expect(screen.getAllByText(/142 nyitott teendő/)).toHaveLength(2);
    const buttons = screen.getAllByRole("button", { name: "Leváltás" });
    fireEvent.click(buttons[1]);
    expect(onSupersede).not.toHaveBeenCalled();
    fireEvent.click(confirmAction());
    expect(onSupersede).toHaveBeenCalledWith("run-000000000002");
  });

  it("names the human work that stays with a run", () => {
    render(<OlderRunsOffer runs={RUNS} busy={false} onSupersede={() => {}} />);
    expect(screen.getAllByText(/kézzel javított irata a régin marad/)).toHaveLength(1);
  });

  it("shows nothing without such a run, and reads in English too", async () => {
    const { container } = render(<OlderRunsOffer runs={[]} busy={false} onSupersede={() => {}} />);
    expect(container.textContent).toBe("");
    await setLanguage("en");
    render(<OlderRunsOffer runs={RUNS.slice(0, 1)} busy={false} onSupersede={() => {}} />);
    expect(screen.getByRole("button", { name: "Supersede" })).toBeTruthy();
    expect(screen.getByText(/1 older live run\(s\) were repeated by a later live run/)).toBeTruthy();
  });
});
