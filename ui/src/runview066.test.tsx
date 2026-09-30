// 066 Á24: the Result section and the approval box did not update even at the end of the run. The shared run view
// refreshes by itself while a run is active, and stops once it is closed (it asks no further).
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type RunView } from "./api";
import { useRunView } from "./hooks";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function Status({ runId }: { runId: string }) {
  const view = useRunView(runId);
  return <span data-testid="status">{view.data?.run.status ?? "-"}</span>;
}

const view = (status: string) => ({ run: { run_id: "run-1", status } }) as unknown as RunView;

describe("Futás-nézet frissítése (066 Á24)", () => {
  it("futás közben frissít, lezárás után leáll", async () => {
    vi.useFakeTimers();
    const spy = vi.spyOn(api, "run")
      .mockResolvedValueOnce(view("running"))
      .mockResolvedValueOnce(view("done"))
      .mockResolvedValue(view("done"));
    render(<Status runId="run-1" />);
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    expect(screen.getByTestId("status").textContent).toBe("running");
    await act(async () => { await vi.advanceTimersByTimeAsync(3100); });
    expect(screen.getByTestId("status").textContent).toBe("done");
    const calls = spy.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(spy.mock.calls.length).toBe(calls);
  });
});
