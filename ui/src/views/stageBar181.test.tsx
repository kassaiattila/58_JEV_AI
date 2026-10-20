// 181 (backlog J-szakaszsav-kiadott-proba): the stage bar's result says a released package's release state, also when
// its latest run is a trial; a package never released still reads as a trial result. Synthetic values only.
import { beforeEach, describe, expect, it } from "vitest";
import type { RunRow, WorkpackageView } from "../api";
import { setLanguage } from "../i18n";
import { stageStatus } from "./WorkpackageDetail";

const TRIAL = { run_id: "run-000000000001", mode: "shadow", status: "done", approval: null, items: 2, items_done: 2,
  open_reasons: 0, created_at: "2026-10-20T10:00:00+00:00" } as unknown as RunRow;

function view(over: Partial<WorkpackageView> = {}): WorkpackageView {
  return { workpackage: { id: "wp-00000000000a", name: "June invoices", source_kind: "folder", status: "open", items: [] },
    readiness: { ready: true }, last_run: TRIAL, current_run: TRIAL, runs: 3,
    next: { code: "go_live", label: "", stage: "process" }, ...over } as unknown as WorkpackageView;
}

beforeEach(async () => { await setLanguage("en"); });

describe("181 the stage bar of a released package", () => {
  it("says the release state after a trial run", () => {
    expect(stageStatus(view({ release: { state: "released", version: 1 } })).result).toBe("released");
    expect(stageStatus(view({ release: { state: "partly_released", version: 2 } })).result).toBe("partly released");
    expect(stageStatus(view({ release: { state: "changed_since_release", version: 2 } })).result).toBe("changed since the release");
  });

  it("still says a trial result for a package never released", () => {
    expect(stageStatus(view()).result).toBe("trial result");
  });
});
