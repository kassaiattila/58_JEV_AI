// 167 (review 160 U-4, U-5): the release line names a stopped, failed or superseded live run for what it is (it cannot
// be approved) instead of "Not finished", and a release refused because the package is not ready says so instead of
// "someone corrected it". 172: a run's own line (chosen in the picker) offers no approval; the package's Approve and
// release does. Artificial data, no service.
import { fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, ApiError, type DsPage, type PackageResult, type RunView, type WorkpackageView } from "./api";
import { setLanguage } from "./i18n";
import { ResultStage } from "./views/ResultStage";

vi.mock("./components/DataTable", async () => {
  const React = await import("react");
  return { DataTable: ({ onPage }: { onPage?: (p: DsPage) => void }) => {
    React.useEffect(() => { onPage?.({ rows: [], result_mark: "m1", review_version: "v1" } as unknown as DsPage); }, []); // eslint-disable-line react-hooks/exhaustive-deps
    return null;
  } };
});

beforeEach(async () => { await setLanguage("en"); });
afterEach(async () => { vi.restoreAllMocks(); await setLanguage("hu"); });

const VIEW = { workpackage: { id: "wp-1", revision: 3 }, last_run: { run_id: "run-1" }, current_run: { run_id: "run-1", status: "done" },
  runs: 1 } as unknown as WorkpackageView;

function runView(status: string, extra: Partial<RunView> = {}): RunView {
  return { run: { run_id: "run-1", mode: "apply", status, approval: null, created_at: "2026-10-17T10:00:00Z" },
    tables: ["datapoints"], open_reasons: {}, review_version: "v1", removed_items: [], ...extra } as unknown as RunView;
}

async function runLine(view: RunView): Promise<HTMLElement> {
  vi.spyOn(api, "run").mockResolvedValue(view);
  const { container } = render(<ResultStage view={VIEW} runId="run-1" onChanged={() => {}} />);
  await waitFor(() => expect(container.querySelector(".release-line")).not.toBeNull());
  return container.querySelector(".release-line") as HTMLElement;
}

async function packageLine(): Promise<HTMLElement> {
  vi.spyOn(api, "run").mockResolvedValue(runView("done"));
  vi.spyOn(api, "packageResult").mockResolvedValue({ workpackage_id: "wp-1", mark: "m1", open_live_runs: ["run-1"], removed_items: 0,
    blockers: [], state: "not_released", versions: [], tables: ["datapoints"],
    items: [{ item_id: "doc-1", kind: "document", file: "a.pdf", tier: "live", run_id: "run-1", final_status: "done", released: false }] } as PackageResult);
  const { container } = render(<ResultStage view={VIEW} onChanged={() => {}} />);
  await waitFor(() => expect(container.querySelector(".release-line")).not.toBeNull());
  return container.querySelector(".release-line") as HTMLElement;
}

it.each([
  ["cancelled", {}, "stopped", "Stopped"],
  ["cancelled", { superseded: { by: "run-2", actor: "A", at: "2026-10-17T11:00:00Z", reasons_closed: 2 } }, "superseded", "Superseded"],
  ["failed", {}, "failed", "Failed"],
])("a %s live run is named for what it is and offers no approval", async (status, extra, state, label) => {
  const line = await runLine(runView(status, extra as Partial<RunView>));
  expect(line.dataset.state).toBe(state);
  expect(line.textContent).toContain(label);
  expect(line.textContent).not.toContain("Not finished");
  expect(line.querySelector("button")).toBeNull();
});

it("a run still running is not finished", async () => {
  const line = await runLine(runView("running"));
  expect(line.dataset.state).toBe("running");
});

it("a release refused as not ready names the reason, not a correction", async () => {
  const line = await packageLine();
  vi.spyOn(api, "releasePackage").mockRejectedValue(new ApiError(409, "not_ready", "a live run of the package is not ready for approval"));
  const button = line.querySelector("button") as HTMLButtonElement;
  await waitFor(() => expect(button.disabled).toBe(false));
  fireEvent.click(button);
  fireEvent.click(button);
  await waitFor(() => expect(line.textContent).toContain("The batch cannot be released: a live run of the package is not ready for approval"));
  expect(line.textContent).not.toContain("changed");
});

it("a revision conflict still asks to look again", async () => {
  const line = await packageLine();
  vi.spyOn(api, "releasePackage").mockRejectedValue(new ApiError(409, "revision_conflict", "changed"));
  const button = line.querySelector("button") as HTMLButtonElement;
  await waitFor(() => expect(button.disabled).toBe(false));
  fireEvent.click(button);
  fireEvent.click(button);
  await waitFor(() => expect(line.querySelector("[role=status]")?.textContent).toContain("changed since it was shown"));
  expect(line.querySelector("[role=status]")?.textContent).not.toContain("cannot be released");
});
