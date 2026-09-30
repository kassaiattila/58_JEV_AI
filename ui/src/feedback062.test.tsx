// 062: four small fixes from the joint walkthrough (decision of 2026-09-29) — the item list's current status, the email
// package's default tab and the probability as a percentage, the details of „Mai munkám” (My work today) as labels, and
// marking the list's default order.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type DsColumn, type DsPage, type EmailTask, type ItemResult } from "./api";
import { cellText, DataTable } from "./components/DataTable";
import { EmailReview } from "./review/EmailReview";
import { activityDetail } from "./views/Activity";
import { defaultResultTable } from "./views/ResultStage";
import { queueStatus } from "./views/ReviewWorkspace";

afterEach(() => vi.restoreAllMocks());

describe("062 felület-javítások", () => {
  it("A: a tétellista a mostani állapotot mutatja — a lezárt teendőjű tétel „rendezve”", () => {
    expect(queueStatus({ status: "done", final_status: "needs_review" }, 0)).toBe("rendezve");
    expect(queueStatus({ status: "done", final_status: "needs_review" }, 2)).toBe("teendő");
    expect(queueStatus({ status: "done", final_status: "done" }, 0)).toBe("lezárva");
    expect(queueStatus({ status: "failed", final_status: null }, 0)).toBe("Hibás");
    expect(queueStatus(undefined, 0)).toBe("még nem futott");
  });

  it("B: levélcsomagnál a Levelek az alapfül; a valószínűség százalékban", () => {
    expect(defaultResultTable(["emails", "tasks", "documents", "datapoints"])).toBe("emails");
    expect(defaultResultTable(["documents", "datapoints", "line_items"])).toBe("datapoints");
    expect(defaultResultTable(["utility"])).toBe("utility");
    const col: DsColumn = { key: "confidence", label: "Valószínűség", kind: "number", hidden: false, labels: null, percent: true };
    expect(cellText(col, 0.97)).toBe("97 %");
    expect(cellText(col, 1)).toBe("100 %");
    expect(cellText(col, null)).toBe("");
  });

  it("C: a „Mai munkám” részlete felirat, nem belső kód", () => {
    expect(activityDetail("reason_resolve", "intent:low_conf:system_notification:0.43")).toMatch(/^Bizonytalan levél-szándék: .*\(0,43\)$/);
    expect(activityDetail("task_decision", "accepted")).toBe("elfogadva");
    expect(activityDetail("run_start", "shadow")).toBe("Próba");
    expect(activityDetail("run_approve", "approved")).toBe("jóváhagyva");
    expect(activityDetail("recipe", "Számlák adatainak kinyerése")).toBe("Számlák adatainak kinyerése");
    expect(activityDetail("mailbox_pull", "minta@pelda.hu")).toBe("minta@pelda.hu");
  });

  it("E: az elfogadott feladat elvégezve jelölhető; az elvégzett a névvel látszik és visszavonható", async () => {
    const done = vi.spyOn(api, "markTaskDone").mockResolvedValue({} as ItemResult);
    const task = (decision: EmailTask["decision"]): EmailTask => ({
      index: 0, action: "provide_document", title: "Számla beküldése", due_date: null, assignee_hint: null,
      evidence: [{ pointer: "/messages/0/body", quote: "várjuk a számládat" }], decision,
    });
    const mail = (decision: EmailTask["decision"]): ItemResult => ({
      run_id: "run-000000000001", item_id: "a".repeat(64), kind: "email", extraction: null, source: null, provenance: {}, open_reasons: [],
      email: { subject: "Számla", sender: null, sender_name: null, to: [], received_at: null, mailbox: null, body: "várjuk a számládat",
        attachments: [], result: { intent: "business_correspondence", intent_label: null, confidence: 0.9, next_flow: "human:inbox",
          attachments: [], from_this_run: true, signals: {} },
        tasks: { status: "proposed", tasks: [task(decision)], rejected: [] } },
    } as unknown as ItemResult);
    const accepted = { decision: "accepted" as const, actor: "Minta Anna", decided_at: "2026-09-29T08:00:00Z" };
    const { unmount } = render(<EmailReview data={mail(accepted)} onChanged={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Elvégezve" }));
    expect(done).toHaveBeenCalledWith("run-000000000001", "a".repeat(64), 0, true);
    unmount();
    render(<EmailReview data={mail({ ...accepted, done_by: "Minta Anna", done_at: "2026-09-29T09:00:00Z" })} onChanged={() => {}} />);
    expect(screen.getByText(/Elvégezte: Minta Anna/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Elvégzés visszavonása" }));
    expect(done).toHaveBeenLastCalledWith("run-000000000001", "a".repeat(64), 0, false);
    render(<EmailReview data={mail(null)} onChanged={() => {}} />);
    expect(screen.queryAllByRole("button", { name: "Elvégezve" })).toHaveLength(0); // without a decision it cannot be marked done
  });

  it("D: rendezés nélkül a szolgáltatás alapsorrendje látszik a fejlécen", async () => {
    const cols: DsColumn[] = [
      { key: "name", label: "Név", kind: "text", hidden: false, labels: null },
      { key: "created_at", label: "Létrehozva", kind: "datetime", hidden: false, labels: null },
    ];
    const pg: DsPage = {
      dataset: { name: "workpackages", label: "Munkacsomagok", scope: [], optional_scope: [], natural_sort: [{ col: "created_at", desc: true }] },
      columns: cols, rows: [{ _key: "wp-1", name: "Minta csomag", created_at: "2026-09-29T01:00:00Z" }], total: 1, matched: 1, offset: 0, limit: 100, facets: {},
    };
    vi.spyOn(api, "datasetQuery").mockResolvedValue(pg);
    const { container } = render(<DataTable dataset="workpackages" label="Munkacsomagok" />);
    await screen.findByText("Minta csomag");
    expect([...container.querySelectorAll(".sort-mark")].map((m) => m.getAttribute("data-dir"))).toEqual(["none", "desc"]);
    const head = screen.getByRole("button", { name: /^Létrehozva/ });
    expect(head.closest("th")?.getAttribute("aria-sort")).toBe("descending");
    expect(head.getAttribute("title")).toContain("Alapsorrend");
  });
});
