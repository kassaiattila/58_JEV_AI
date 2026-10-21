// 187 (plan G-full-move T2c): a reconciliation package's decisions send back the package's journal state as the page
// last read it, so the service refuses a decision made on a page that is stale by now; each package keeps its own.
import { afterEach, expect, it, vi } from "vitest";
import { api } from "./api";

afterEach(() => { vi.restoreAllMocks(); });

/** A service that answers every request with the given body; the requests' bodies are kept. */
function service(answer: Record<string, unknown>) {
  const sent: Record<string, unknown>[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_url, init) => {
    if (init?.body) sent.push(JSON.parse(String(init.body)) as Record<string, unknown>);
    return new Response(JSON.stringify(answer), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  return sent;
}

it("sends back the journal state the page last read, and the newer one after its own decision", async () => {
  service({ workpackage_id: "wp-00000000000a", journal_state: 7 });
  await api.reconcileWorkspace("wp-00000000000a");
  vi.restoreAllMocks();
  let sent = service({ workpackage_id: "wp-00000000000a", journal_state: 9 });
  await api.reconcileMark("wp-00000000000a", ["line-1"], "fee");
  expect(sent[0]).toEqual({ line_ids: ["line-1"], category: "fee", expected_state: 7 });
  vi.restoreAllMocks();
  sent = service({ accepted: 1, review: {}, workspace: { journal_state: 10 } });
  await api.reconcileQuickAccept("wp-00000000000a", "sure_pairs", ["line-2"]);
  expect(sent[0]).toEqual({ group: "sure_pairs", line_ids: ["line-2"], expected_state: 9 });
  vi.restoreAllMocks();
  sent = service({ workpackage_id: "wp-00000000000a", journal_state: 11 });
  await api.reconcileAcceptProposed("wp-00000000000a");
  expect(sent[0]).toEqual({ expected_state: 10 });
});

it("sends nothing for a package it has not read, and keeps each package's own state", async () => {
  service({ workpackage_id: "wp-00000000000b", journal_state: 3 });
  await api.reconcileStatement("wp-00000000000b");
  vi.restoreAllMocks();
  const sent = service({ workpackage_id: "wp-00000000000c", journal_state: 1 });
  await api.reconcileUnmark("wp-00000000000c", ["line-3"]);
  await api.reconcileLeaveOut("wp-00000000000b", ["doc-1"], "not ours");
  expect(sent).toEqual([{ line_ids: ["line-3"] }, { doc_ids: ["doc-1"], reason: "not ours", expected_state: 3 }]);
});
