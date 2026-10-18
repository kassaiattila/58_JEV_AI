// 156: the Result section's release line, one line with the state's own mark (never the action colour); the approval
// is the view's solid main action only when it can be given. 172 (DECISIONS 167, 172): by default the line is the
// package's — its current result and its one Approve and release — and a run chosen in the picker shows its own state
// with no approval of its own. Artificial data, no service.
import { render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, type DsPage, type PackageResult, type RunView, type WorkpackageView } from "./api";
import { setLanguage } from "./i18n";
import { ResultStage } from "./views/ResultStage";

// the table reports the mark of its rows once loaded: until then there is nothing to release (086)
vi.mock("./components/DataTable", async () => {
  const React = await import("react");
  return { DataTable: ({ onPage }: { onPage?: (p: DsPage) => void }) => {
    React.useEffect(() => { onPage?.({ rows: [], result_mark: "m1", review_version: "v1" } as unknown as DsPage); }, []); // eslint-disable-line react-hooks/exhaustive-deps
    return <div data-testid="table" />;
  } };
});

beforeEach(async () => { await setLanguage("en"); });
afterEach(async () => { vi.restoreAllMocks(); await setLanguage("hu"); });

const VIEW = { workpackage: { id: "wp-1", revision: 3 }, last_run: { run_id: "run-1" }, current_run: { run_id: "run-1", status: "done" },
  runs: 1 } as unknown as WorkpackageView;

function packageResult(over: Partial<PackageResult> = {}): PackageResult {
  return { workpackage_id: "wp-1", mark: "m1", open_live_runs: ["run-1"], removed_items: 0, blockers: [], state: "not_released",
    versions: [], tables: ["datapoints"],
    items: [{ item_id: "doc-1", kind: "document", file: "a.pdf", tier: "live", run_id: "run-1", final_status: "done", released: false }],
    ...over };
}

function stubRun(run: Record<string, unknown> = { mode: "apply", status: "done", approval: null }, openReasons: Record<string, string[]> = {}) {
  vi.spyOn(api, "run").mockResolvedValue({ run: { run_id: "run-1", ...run }, tables: ["datapoints"], open_reasons: openReasons,
    review_version: "v1" } as unknown as RunView);
  vi.spyOn(api, "datasetQuery").mockResolvedValue({ rows: [], review_version: "v1" } as unknown as DsPage);
}

function showPackage(result: PackageResult, view: WorkpackageView = VIEW) {
  stubRun();
  vi.spyOn(api, "packageResult").mockResolvedValue(result);
  return render(<ResultStage view={view} onChanged={() => {}} />).container;
}

async function line(container: HTMLElement): Promise<HTMLElement> {
  await waitFor(() => expect(container.querySelector(".release-line")).not.toBeNull());
  return container.querySelector(".release-line") as HTMLElement;
}

it("a package with only a trial's result says it cannot be released and offers no release", async () => {
  const el = await line(showPackage(packageResult({ open_live_runs: [], blockers: [{ code: "nothing_to_release" }],
    items: [{ item_id: "doc-1", kind: "document", file: "a.pdf", tier: "trial", run_id: "run-1", final_status: "done", released: false }] })));
  expect(el.dataset.state).toBe("trial");
  expect(el.querySelector("button")).toBeNull();
});

it("open to-dos show their count with the to-do mark, and the release waits", async () => {
  const el = await line(showPackage(packageResult({ blockers: [{ code: "run_not_ready", run_id: "run-1", status: "needs_review", open_reasons: 3 }] })));
  expect(el.dataset.state).toBe("todo");
  expect(el.querySelector(".status")?.classList.contains("s-needs_review")).toBe(true);
  expect(el.querySelector(".status")?.textContent).toContain("3");
  const button = el.querySelector("button") as HTMLButtonElement;
  expect(button.disabled).toBe(true);
  expect(button.className).not.toContain("primary");
});

it("finished live results with no to-dos make Approve and release the solid main action", async () => {
  const el = await line(showPackage(packageResult()));
  expect(el.dataset.state).toBe("ready");
  expect(el.querySelector(".status")?.textContent).toBe("Awaiting release");
  expect(el.textContent).toContain("version 1");
  await waitFor(() => expect((el.querySelector("button") as HTMLButtonElement).disabled).toBe(false));
  expect(el.querySelector("button")?.className).toBe("primary");
  expect(el.querySelector("button")?.textContent).toBe("Approve and release");
});

it("a released package shows the done mark, its version and who released it, and its stored download", async () => {
  const v = { version: 2, mark: "m1", items: [["doc-1", "run-1"]] as [string, string][], runs: ["run-1"], released_by: "Example Person",
    released_at: "2026-10-16T08:00:00+00:00", backfilled_at: null,
    files: [{ name: "result.xlsx", media: "x", rows: 1, sha256: "a" }, { name: "line_items.csv", media: "x", rows: 0, sha256: "b" }] };
  const container = showPackage(packageResult({ state: "released", open_live_runs: [], blockers: [{ code: "nothing_to_release" }], versions: [v],
    items: [{ item_id: "doc-1", kind: "document", file: "a.pdf", tier: "approved", run_id: "run-1", final_status: "done", released: true }] }));
  const el = await line(container);
  expect(el.dataset.state).toBe("released");
  expect(el.querySelector(".status")?.classList.contains("s-done")).toBe(true);
  expect(el.textContent).toContain("version 2");
  expect(el.textContent).toContain("Example Person");
  expect(el.querySelector("button")).toBeNull();
  expect(el.querySelector("a[download]")?.getAttribute("href")).toBe("/api/workpackages/wp-1/versions/2/files/result.xlsx");
  // the versions' fold lists each stored download; an empty CSV table is left out
  const fold = container.querySelector("details.release-versions") as HTMLElement;
  expect(fold.querySelector("summary")?.textContent).toBe("Released versions (1)");
  expect([...fold.querySelectorAll("a")].map((a) => a.textContent)).toEqual(["Excel"]);
});

it("a version recorded afterwards says so", async () => {
  const v = { version: 1, mark: "m1", items: [], runs: [], released_by: "Example Person", released_at: "2026-10-01T08:00:00+00:00",
    backfilled_at: "2026-10-18T12:00:00+00:00", files: [] };
  const el = await line(showPackage(packageResult({ state: "released", open_live_runs: [], blockers: [{ code: "nothing_to_release" }], versions: [v] })));
  expect(el.textContent).toContain("recorded afterwards");
});

it("a live run still running shows the running mark", async () => {
  const running = { ...VIEW, current_run: { run_id: "run-2", status: "running" } } as unknown as WorkpackageView;
  const el = await line(showPackage(packageResult({ open_live_runs: [], blockers: [{ code: "nothing_to_release" }] }), running));
  expect(el.dataset.state).toBe("running");
  expect(el.querySelector(".status")?.classList.contains("s-running")).toBe(true);
});

it("items from a trial are named as shown but not released", async () => {
  const el = await line(showPackage(packageResult({ items: [
    { item_id: "doc-1", kind: "document", file: "a.pdf", tier: "live", run_id: "run-1", final_status: "done", released: false },
    { item_id: "doc-2", kind: "document", file: "b.pdf", tier: "trial", run_id: "run-2", final_status: "done", released: false }] })));
  expect(el.querySelector(".status.s-trial")?.textContent).toBe("1 from a trial");
  expect(el.textContent).toContain("shown here, not released");
});

it("a run chosen in the picker shows its own state and leads to the package's result, with no approval of its own", async () => {
  stubRun();
  vi.spyOn(api, "packageResult").mockResolvedValue(packageResult());
  const { container } = render(<ResultStage view={VIEW} runId="run-1" onChanged={() => {}} />);
  const el = await line(container);
  expect(el.dataset.state).toBe("ready");
  expect(el.querySelector("button")).toBeNull();
  expect(el.querySelector("a")?.getAttribute("href")).toBe("#/workpackages/wp-1/result");
});

it("a released run reads approved, by whom", async () => {
  stubRun({ mode: "apply", status: "done", approval: "approved", approved_by: "Example Person", approved_at: "2026-10-16T08:00:00+00:00" });
  const { container } = render(<ResultStage view={VIEW} runId="run-1" onChanged={() => {}} />);
  const el = await line(container);
  expect(el.dataset.state).toBe("released");
  expect(el.querySelector(".status")?.textContent).toBe("Approved");
  expect(el.textContent).toContain("Example Person");
});
