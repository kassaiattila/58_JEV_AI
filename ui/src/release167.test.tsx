// 167 (review 160 U-4, U-5): the release line names a stopped, failed or superseded live run for what it is (it cannot
// be approved) instead of "Not finished", and an approval refused because the run is not ready says so instead of
// "someone corrected it". Artificial data, no service.
import { fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, ApiError, type DsPage, type RunView, type WorkpackageView } from "./api";
import { setLanguage } from "./i18n";
import { ResultStage } from "./views/ResultStage";

vi.mock("./components/DataTable", async () => {
  const React = await import("react");
  return { DataTable: ({ onPage }: { onPage?: (p: DsPage) => void }) => {
    React.useEffect(() => { onPage?.({ rows: [], review_version: "v1" } as unknown as DsPage); }, []); // eslint-disable-line react-hooks/exhaustive-deps
    return null;
  } };
});

beforeEach(async () => { await setLanguage("en"); });
afterEach(async () => { vi.restoreAllMocks(); await setLanguage("hu"); });

const VIEW = { workpackage: { id: "wp-1" }, last_run: { run_id: "run-1" }, runs: 1 } as unknown as WorkpackageView;

function runView(status: string, extra: Partial<RunView> = {}): RunView {
  return { run: { run_id: "run-1", mode: "apply", status, approval: null, created_at: "2026-10-17T10:00:00Z" },
    tables: ["datapoints"], open_reasons: {}, review_version: "v1", removed_items: [], ...extra } as unknown as RunView;
}

async function releaseLine(view: RunView): Promise<HTMLElement> {
  vi.spyOn(api, "run").mockResolvedValue(view);
  const { container } = render(<ResultStage view={VIEW} onChanged={() => {}} />);
  await waitFor(() => expect(container.querySelector(".release-line")).not.toBeNull());
  return container.querySelector(".release-line") as HTMLElement;
}

it.each([
  ["cancelled", {}, "stopped", "Stopped"],
  ["cancelled", { superseded: { by: "run-2", actor: "A", at: "2026-10-17T11:00:00Z", reasons_closed: 2 } }, "superseded", "Superseded"],
  ["failed", {}, "failed", "Failed"],
])("a %s live run is named for what it is and offers no approval", async (status, extra, state, label) => {
  const line = await releaseLine(runView(status, extra as Partial<RunView>));
  expect(line.dataset.state).toBe(state);
  expect(line.textContent).toContain(label);
  expect(line.textContent).not.toContain("Not finished");
  expect(line.querySelector("button")).toBeNull();
});

it("a run still running is not finished", async () => {
  const line = await releaseLine(runView("running"));
  expect(line.dataset.state).toBe("running");
});

it("an approval refused as not ready names the reason, not a correction", async () => {
  const line = await releaseLine(runView("done"));
  vi.spyOn(api, "approve").mockRejectedValue(new ApiError(409, "not_ready", "The run still has open review reasons"));
  const button = line.querySelector("button") as HTMLButtonElement;
  await waitFor(() => expect(button.disabled).toBe(false));
  fireEvent.click(button);
  fireEvent.click(button);
  await waitFor(() => expect(line.textContent).toContain("The run cannot be approved: The run still has open review reasons"));
  expect(line.textContent).not.toContain("changed");
});

it("a revision conflict still asks to look again", async () => {
  const line = await releaseLine(runView("done"));
  vi.spyOn(api, "approve").mockRejectedValue(new ApiError(409, "revision_conflict", "changed"));
  const button = line.querySelector("button") as HTMLButtonElement;
  await waitFor(() => expect(button.disabled).toBe(false));
  fireEvent.click(button);
  fireEvent.click(button);
  await waitFor(() => expect(line.querySelector("[role=status]")?.textContent).toBeTruthy());
  expect(line.querySelector("[role=status]")?.textContent).not.toContain("cannot be approved");
});
