// 218 (plan G-process-core P3a; the owner's decision of 2026-10-23: shown at the approval, nothing stops): when some
// items of a live run were processed with other rules or another version of the program than the run started with
// (a release during the run), the package's Approve and release and the run's own line say how many and which rule
// files changed, with their versions; the approval stays the one main action. A run without changes, and a view from
// an older service, show nothing. Artificial data, no service.
import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type DsPage, type PackageResult, type RuleChanges, type RunView, type WorkpackageView } from "./api";
import { setLanguage } from "./i18n";
import { ResultStage } from "./views/ResultStage";

vi.mock("./components/DataTable", async () => {
  const React = await import("react");
  return { DataTable: ({ onPage }: { onPage?: (p: DsPage) => void }) => {
    React.useEffect(() => { onPage?.({ rows: [], review_version: "v1" } as unknown as DsPage); }, []); // eslint-disable-line react-hooks/exhaustive-deps
    return <div data-testid="table" />;
  } };
});

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const VIEW = { workpackage: { id: "wp-1", revision: 1 }, last_run: { run_id: "run-1" }, current_run: { run_id: "run-1", status: "done" },
  runs: 1 } as unknown as WorkpackageView;

const FILES = [
  { path: "policy.json", before: "1.25.0", after: "1.26.0" }, { path: "email_rules.json", before: null, after: "1.0.0" },
  { path: "reconcile.json", before: "1.14.0", after: "1.15.0" }, { path: "prompts/a.md", before: null, after: null },
];

function release(changes?: RuleChanges, runId?: string) {
  vi.spyOn(api, "run").mockResolvedValue({ run: { run_id: "run-1", mode: "apply", status: "done", approval: null },
    tables: ["datapoints"], open_reasons: {}, review_version: "v1", engine: "jev", budget: { providers: { jev: { limit_usd: "0.10", committed_usd: "0" } } },
    ...(changes ? { rule_changes: changes } : {}) } as unknown as RunView);
  vi.spyOn(api, "datasetQuery").mockResolvedValue({ rows: [], review_version: "v1", result_mark: "m1" } as unknown as DsPage);
  vi.spyOn(api, "packageResult").mockResolvedValue({ workpackage_id: "wp-1", mark: "m1", open_live_runs: ["run-1"], removed_items: 0,
    blockers: [], state: "not_released", versions: [], tables: ["datapoints"],
    items: [{ item_id: "doc-1", kind: "document", file: "a.pdf", tier: "live", run_id: "run-1", final_status: "done", released: false }] } as PackageResult);
  return render(<ResultStage view={VIEW} runId={runId} onChanged={() => {}} />).container;
}

describe("rules that changed during a run are shown at its approval", () => {
  it("the package's release names the items and the first rule files with their versions", async () => {
    const container = release({ items: 2, snapshots: 2, code_changed: false, files: FILES });
    await waitFor(() => expect(container.querySelector(".release-line .release-note")).not.toBeNull());
    const note = container.querySelector(".release-line .release-note") as HTMLElement;
    expect(note.querySelector(".status")?.textContent).toBe("Rules changed");
    expect(note.querySelector(".status")?.className).toContain("s-warn");
    expect(note.querySelector(".release-detail")?.textContent).toBe(
      "2 item(s) processed with other rules than the run started with: policy.json 1.25.0 → 1.26.0, "
      + "email_rules.json – → 1.0.0, reconcile.json 1.14.0 → 1.15.0 and 1 more");
    expect(container.querySelector(".release-line button")?.className).toBe("primary"); // nothing stops the approval
  });

  it("a change of the program alone, or with the rules, says so", async () => {
    const code = release({ items: 1, snapshots: 2, code_changed: true, files: [] });
    await waitFor(() => expect(code.querySelector(".release-note .release-detail")?.textContent).toBe(
      "1 item(s) processed with another version of the program than the run started with"));
    cleanup();
    const both = release({ items: 1, snapshots: 2, code_changed: true, files: FILES.slice(0, 1) });
    await waitFor(() => expect(both.querySelector(".release-note .release-detail")?.textContent).toBe(
      "1 item(s) processed with another version of the program and other rules than the run started with: policy.json 1.25.0 → 1.26.0"));
  });

  it("a run's own line shows it too; a run without changes shows nothing", async () => {
    const own = release({ items: 1, snapshots: 2, code_changed: false, files: FILES.slice(0, 1) }, "run-1");
    await waitFor(() => expect(own.querySelector(".release-line .release-note")).not.toBeNull());
    cleanup();
    const none = release(undefined, "run-1");
    await waitFor(() => expect(none.querySelector(".release-line .engine-mark")).not.toBeNull());
    expect(none.querySelector(".release-note")).toBeNull();
  });
});
