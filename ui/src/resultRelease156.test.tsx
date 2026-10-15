// 156: the Result section's release line. The shown run's state is one line with its own state mark (never the action
// colour); the approval is the view's solid main action only when it can be given. Artificial data, no service.
import { render, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api, type DsPage, type RunView, type WorkpackageView } from "./api";
import { ResultStage } from "./views/ResultStage";

// the table reports its rows' version once loaded: until then there is nothing to approve (086)
vi.mock("./components/DataTable", async () => {
  const React = await import("react");
  return { DataTable: ({ onPage }: { onPage?: (p: DsPage) => void }) => {
    React.useEffect(() => { onPage?.({ rows: [], review_version: "v1" } as unknown as DsPage); }, []); // eslint-disable-line react-hooks/exhaustive-deps
    return <div data-testid="table" />;
  } };
});

afterEach(() => vi.restoreAllMocks());

const VIEW = { workpackage: { id: "wp-1" }, last_run: { run_id: "run-1" }, runs: 1 } as unknown as WorkpackageView;

function show(run: Record<string, unknown>, openReasons: Record<string, string[]> = {}) {
  vi.spyOn(api, "run").mockResolvedValue({ run: { run_id: "run-1", ...run }, tables: ["datapoints"], open_reasons: openReasons,
    review_version: "v1" } as unknown as RunView);
  vi.spyOn(api, "datasetQuery").mockResolvedValue({ rows: [], review_version: "v1" } as unknown as DsPage);
  return render(<ResultStage view={VIEW} onChanged={() => {}} />).container;
}

async function line(container: HTMLElement): Promise<HTMLElement> {
  await waitFor(() => expect(container.querySelector(".release-line")).not.toBeNull());
  return container.querySelector(".release-line") as HTMLElement;
}

it("a trial result says it cannot be released and offers no approval", async () => {
  const el = await line(show({ mode: "shadow", status: "done", approval: null, created_at: "2026-10-16T08:00:00+00:00" }));
  expect(el.dataset.state).toBe("trial");
  expect(el.querySelector("button")).toBeNull();
});

it("open to-dos show their count with the to-do mark, and the approval waits", async () => {
  const el = await line(show({ mode: "apply", status: "needs_review", approval: null }, { "doc-1": ["pick"], "doc-2": ["pick", "money"] }));
  expect(el.dataset.state).toBe("todo");
  expect(el.querySelector(".status")?.classList.contains("s-needs_review")).toBe(true);
  expect(el.querySelector(".status")?.textContent).toContain("3");
  const button = el.querySelector("button") as HTMLButtonElement;
  expect(button.disabled).toBe(true);
  expect(button.className).not.toContain("primary");
});

it("a finished live run with no to-dos makes the approval the solid main action", async () => {
  const el = await line(show({ mode: "apply", status: "done", approval: null }));
  expect(el.dataset.state).toBe("ready");
  await waitFor(() => expect((el.querySelector("button") as HTMLButtonElement).disabled).toBe(false));
  expect(el.querySelector("button")?.className).toBe("primary");
});

it("a released run shows the done mark and who released it", async () => {
  const el = await line(show({ mode: "apply", status: "done", approval: { at: "x" }, approved_by: "Example Person",
    approved_at: "2026-10-16T08:00:00+00:00" }));
  expect(el.dataset.state).toBe("released");
  expect(el.querySelector(".status")?.classList.contains("s-done")).toBe(true);
  expect(el.textContent).toContain("Example Person");
  expect(el.querySelector("button")).toBeNull();
});

it("a live run still running shows the running mark", async () => {
  const el = await line(show({ mode: "apply", status: "running", approval: null }));
  expect(el.dataset.state).toBe("running");
  expect(el.querySelector(".status")?.classList.contains("s-running")).toBe(true);
});
