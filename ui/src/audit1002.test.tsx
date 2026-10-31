// 086 (audit of 2026-10-02, N01): the approval names the version of the result the table on screen shows. After a
// conflict the table is loaded again; until the new rows have arrived there is nothing to approve, and the next
// approval names the version of the rows now shown. The audit's witness, turned round. 172: the package's Approve and
// release names the mark of the package's result its table shows (`result_mark`). Artificial data, no service.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api, ApiError, type DsPage, type PackageResult, type RunView, type WorkpackageView } from "./api";
import { ResultStage } from "./views/ResultStage";
import { confirmAction } from "./confirm.testutil";

vi.mock("./components/DataTable", async () => {
  const React = await import("react");
  return { DataTable: ({ dataset, scope, onPage }: { dataset: string; scope: Record<string, string>; onPage?: (p: DsPage) => void }) => {
    const [value, setValue] = React.useState("");
    React.useEffect(() => {
      void api.datasetQuery(dataset, scope, {}).then((r) => { setValue(String(r.rows[0].value)); onPage?.(r); });
    }, []); // eslint-disable-line react-hooks/exhaustive-deps
    return <div data-testid="displayed-result">{value}</div>;
  } };
});

afterEach(() => vi.restoreAllMocks());

it.each(["datapoints", "native_facts"])("after a conflict only the mark of the %s rows on screen can be released", async (table) => {
  let current = "m1";
  vi.spyOn(api, "run").mockResolvedValue({ run: { run_id: "run-1", mode: "apply", status: "done", approval: null },
    tables: [table], open_reasons: {}, review_version: "v1" } as unknown as RunView);
  vi.spyOn(api, "packageResult").mockImplementation(async () => ({ workpackage_id: "wp-1", mark: current, open_live_runs: ["run-1"],
    removed_items: 0, blockers: [], state: "not_released", versions: [], tables: [table],
    items: [{ item_id: "doc-1", kind: "document", file: "a.pdf", tier: "live", run_id: "run-1", final_status: "done", released: false }] }) as PackageResult);
  let release!: () => void;
  const dataset = vi.spyOn(api, "datasetQuery").mockImplementation(async () => {
    const mark = current;
    if (mark === "m2") await new Promise<void>((resolve) => { release = resolve; }); // a slow reload
    return { rows: [{ value: mark === "m1" ? "OLD" : "NEW" }], result_mark: mark } as unknown as DsPage;
  });
  const give = vi.spyOn(api, "releasePackage").mockRejectedValueOnce(new ApiError(409, "revision_conflict", "changed")).mockResolvedValue({} as never);
  const view = { workpackage: { id: "wp-1", revision: 1 }, last_run: { run_id: "run-1" }, current_run: { run_id: "run-1", status: "done" },
    runs: 1 } as unknown as WorkpackageView;
  render(<ResultStage view={view} onChanged={() => {}} />);
  await screen.findByText("OLD");
  expect(dataset.mock.calls[0][1]).toEqual({ workpackage_id: "wp-1" }); // the package's current result
  const button = () => screen.getByRole("button", { name: "Jóváhagyás és kiadás" });
  await waitFor(() => expect(button().hasAttribute("disabled")).toBe(false));

  const loadsBefore = dataset.mock.calls.length;
  current = "m2"; // someone saves a correction in another tab
  fireEvent.click(button());
  fireEvent.click(confirmAction());
  await screen.findByText(/A köteg eredménye a megtekintés óta változott/);
  expect(give.mock.calls[0][1]).toBe("m1");
  // the table is loading again: the new result cannot be released with the old rows on screen
  await waitFor(() => expect(dataset.mock.calls.length).toBe(loadsBefore + 1));
  expect(screen.getByTestId("displayed-result").textContent).not.toBe("NEW"); // the table is loaded afresh
  expect(button().hasAttribute("disabled")).toBe(true);

  release();
  await screen.findByText("NEW");
  await waitFor(() => expect(button().hasAttribute("disabled")).toBe(false));
  fireEvent.click(button());
  fireEvent.click(confirmAction());
  await waitFor(() => expect(give).toHaveBeenCalledTimes(2));
  expect(give.mock.calls[1][1]).toBe("m2");
  expect(screen.getByTestId("displayed-result").textContent).toBe("NEW");
});
