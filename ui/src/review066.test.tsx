// 066 review: the fixes affecting the UI (the download's file name, the fresh budget on the confirmation page).
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, filenameFromDisposition, type Readiness, type WorkpackageView } from "./api";
import { StartConfirm } from "./views/StartConfirm";

describe("066 Á22: a letöltés fájlneve", () => {
  it("az ékezetes pontos nevet adja, ha a szolgáltatás küldi", () => {
    const disp = "attachment; filename=\"activity-Komuves_Odon-all.csv\"; filename*=UTF-8''activity-K%C5%91m%C5%B1ves%20%C3%96d%C3%B6n-all.csv";
    expect(filenameFromDisposition(disp)).toBe("activity-Kőműves Ödön-all.csv");
  });

  it("a régi fejlécből az ASCII-nevet, fejléc nélkül a tartalék nevet adja", () => {
    expect(filenameFromDisposition("attachment; filename=\"futas.xlsx\"")).toBe("futas.xlsx");
    expect(filenameFromDisposition("")).toBe("letoltes");
  });
});

describe("066 Á12: a megerősítő oldal friss keretet mutat", () => {
  afterEach(() => vi.restoreAllMocks());

  it("a csomag régi nézete helyett a friss keretet és ujjlenyomatot használja; addig az indítás tiltva", async () => {
    const user = userEvent.setup();
    const old = view();
    let answer: (r: Readiness) => void = () => {};
    vi.spyOn(api, "readiness").mockReturnValue(new Promise<Readiness>((res) => { answer = res; }));
    vi.spyOn(api, "recipes").mockResolvedValue({ recipes: [] });
    const start = vi.spyOn(api, "start").mockResolvedValue({ run_id: "run-000000000009", deduped: false } as Awaited<ReturnType<typeof api.start>>);
    render(<StartConfirm view={old} mode="shadow" rerun={false} onChanged={() => {}} />);
    const button = await screen.findByRole("button", { name: "Próbafutás indítása" });
    expect(button.hasAttribute("disabled")).toBe(true);
    expect(screen.getByText("A költségkeret frissítése…")).toBeTruthy();
    answer({ ...old.readiness, budget: { jev: "0.3", openai: "0.5" }, input_hash: "fedcba9876543210" });
    await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
    expect(screen.getByText(/JEV legfeljebb 0,30 USD, OpenAI legfeljebb 0,50 USD/)).toBeTruthy();
    await user.click(button);
    expect(start).toHaveBeenCalledWith("wp-1", { mode: "shadow", expected_revision: 1, input_hash: "fedcba9876543210" });
  });
});

function view(): WorkpackageView {
  return {
    workpackage: {
      id: "wp-1", name: "Minta", source_kind: "manual", source_ref: null, revision: 1, status: "open", created_at: "2026-09-29T10:00:00Z",
      updated_at: "2026-09-29T10:00:00Z", items: [{ item_id: "a", kind: "document", source_path: "C:/x/a.pdf", sha256: "a", added_revision: 1 }],
      assignment: { workpackage_id: "wp-1", revision: 1, recipe_id: "invoice-extraction", recipe_version: 2, recipe_hash: "h", params: { arm: "S" },
        actor: "Teszt Elek", note: null, created_at: "2026-09-29T10:00:00Z" },
    },
    readiness: { workpackage_id: "wp-1", ready: true, blockers: [], warnings: [], counts: { items: 1 }, budget: { jev: "0.1" }, assignment_revision: 1, input_hash: "0123456789abcdef" },
    next: { code: "start", label: "Próbafutás indítása", stage: "process" }, last_run: null, runs: 0,
  };
}
