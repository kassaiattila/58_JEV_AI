// 265 (code review APPW-01): a live run whose result the release page does not show (it would replace an approved one)
// is named on the release line, and Approve and release waits until it is checked and approved on its own page.
// Artificial data, no service.
import { render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, type DsPage, type PackageResult, type RunView, type WorkpackageView } from "./api";
import { setLanguage } from "./i18n";
import { ResultStage } from "./views/ResultStage";

vi.mock("./components/DataTable", async () => {
  const React = await import("react");
  return { DataTable: ({ onPage }: { onPage?: (p: DsPage) => void }) => {
    React.useEffect(() => { onPage?.({ rows: [], result_mark: "m1" } as unknown as DsPage); }, []); // eslint-disable-line react-hooks/exhaustive-deps
    return null;
  } };
});

beforeEach(async () => { await setLanguage("en"); });
afterEach(async () => { vi.restoreAllMocks(); await setLanguage("hu"); });

const VIEW = { workpackage: { id: "wp-1", revision: 3 }, last_run: { run_id: "run-2" }, current_run: { run_id: "run-2", status: "done" },
  runs: 2 } as unknown as WorkpackageView;

it("a live run whose result is not shown asks to check it first and offers no release", async () => {
  vi.spyOn(api, "run").mockResolvedValue({ run: { run_id: "run-2", mode: "apply", status: "done", approval: null,
    created_at: "2026-10-31T10:00:00Z" }, tables: ["datapoints"], open_reasons: {}, review_version: "v2", removed_items: [] } as unknown as RunView);
  vi.spyOn(api, "packageResult").mockResolvedValue({ workpackage_id: "wp-1", mark: "m1", open_live_runs: ["run-2"], removed_items: 0,
    blockers: [{ code: "run_result_not_shown", run_id: "run-2" }], state: "released", versions: [], tables: ["datapoints"],
    items: [{ item_id: "doc-1", kind: "document", file: "a.pdf", tier: "approved", run_id: "run-1", final_status: "done", released: true }],
  } as PackageResult);
  const { container } = render(<ResultStage view={VIEW} onChanged={() => {}} />);
  await waitFor(() => expect(container.querySelector(".release-line")).not.toBeNull());
  const line = container.querySelector(".release-line") as HTMLElement;
  expect(line.dataset.state).toBe("unseen");
  expect(line.textContent).toContain("Check the new live run first");
  const button = line.querySelector("button") as HTMLButtonElement;
  expect(button.disabled).toBe(true);
});
