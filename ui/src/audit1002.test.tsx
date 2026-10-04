// 086 (audit of 2026-10-02, N01): the approval names the version of the result the table on screen shows. After a
// conflict the table is loaded again; until the new rows have arrived there is nothing to approve, and the next
// approval names the version of the rows now shown. The audit's witness, turned round. Artificial data, no service.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api, ApiError, type DsPage, type RunView, type WorkpackageView } from "./api";
import { ResultStage } from "./views/ResultStage";

vi.mock("./components/DataTable", async () => {
  const React = await import("react");
  return { DataTable: ({ dataset, scope, onPage }: { dataset: string; scope: { run_id: string }; onPage?: (p: DsPage) => void }) => {
    const [value, setValue] = React.useState("");
    React.useEffect(() => {
      void api.datasetQuery(dataset, scope, {}).then((r) => { setValue(String(r.rows[0].value)); onPage?.(r); });
    }, [scope.run_id]); // eslint-disable-line react-hooks/exhaustive-deps
    return <div data-testid="displayed-result">{value}</div>;
  } };
});

afterEach(() => vi.restoreAllMocks());

it.each(["datapoints", "native_facts"])("after a conflict only the version of the %s rows on screen can be approved", async (table) => {
  let current = "v1";
  vi.spyOn(api, "run").mockImplementation(async () => ({ run: { run_id: "run-1", mode: "apply", status: "done", approval: null },
    tables: [table], open_reasons: {}, review_version: current }) as unknown as RunView);
  let release!: () => void;
  const dataset = vi.spyOn(api, "datasetQuery").mockImplementation(async () => {
    const version = current;
    if (version === "v2") await new Promise<void>((resolve) => { release = resolve; }); // a slow reload
    return { rows: [{ value: version === "v1" ? "OLD" : "NEW" }], review_version: version } as unknown as DsPage;
  });
  const approve = vi.spyOn(api, "approve").mockRejectedValueOnce(new ApiError(409, "revision_conflict", "changed")).mockResolvedValue({} as never);
  const view = { workpackage: { id: "wp-1" }, last_run: { run_id: "run-1" }, runs: 1 } as unknown as WorkpackageView;
  render(<ResultStage view={view} onChanged={() => {}} />);
  await screen.findByText("OLD");
  const button = () => screen.getByRole("button", { name: "Jóváhagyás és kiadás" });
  await waitFor(() => expect(button().hasAttribute("disabled")).toBe(false));

  const loadsBefore = dataset.mock.calls.length;
  current = "v2"; // someone saves a correction in another tab
  fireEvent.click(button());
  fireEvent.click(screen.getByRole("button", { name: "Biztosan? Kattints újra" }));
  await screen.findByText(/Az eredmény a megtekintés óta változott/);
  expect(approve.mock.calls[0][1]).toBe("v1");
  // the table is loading again: the new version cannot be approved with the old rows on screen
  await waitFor(() => expect(dataset.mock.calls.length).toBe(loadsBefore + 1));
  expect(screen.getByTestId("displayed-result").textContent).not.toBe("NEW"); // the table is loaded afresh
  expect(button().hasAttribute("disabled")).toBe(true);

  release();
  await screen.findByText("NEW");
  await waitFor(() => expect(button().hasAttribute("disabled")).toBe(false));
  fireEvent.click(button());
  fireEvent.click(screen.getByRole("button", { name: "Biztosan? Kattints újra" }));
  await waitFor(() => expect(approve).toHaveBeenCalledTimes(2));
  expect(approve.mock.calls[1][1]).toBe("v2");
  expect(screen.getByTestId("displayed-result").textContent).toBe("NEW");
});
