// 231 (stage D, D-f8): a letter that goes with a printed document: the draft from its frame, changed and accepted with
// the page's document version; a marker left in it or an address that is none keeps it from being accepted; the
// accepted letter shows its email file with its download and fingerprint. Invented data, a mocked service.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type CaseView, type LetterData } from "../api";
import { setLanguage } from "../i18n";
import { elementOf } from "./registry";

beforeEach(async () => { await setLanguage("en"); });
afterEach(() => { vi.restoreAllMocks(); });

const CASE = "wp-0000000d0f80";
const SHA = "cd34ef56ab12".padEnd(64, "0");
const missing = { state: "missing" as const, step: "letter", active: null, versions: [], returned: null, outdated: null };
const document = { step: "document", version: 3, output: "rated_offer", name: "biztositasi-ajanlat-Minta-Kft-v3.docx", sha256: SHA };
const waiting = (over: Partial<LetterData> = {}): LetterData => ({
  frame: "offer_letter", document, problem: null, basis: { document: 1 }, approval: missing, waits: true, accepted: null,
  draft: { to: "anna@minta.hu", subject: "Biztosítási ajánlat – Minta Kft.", body: "Tisztelt Minta Anna!\n\nAz éves díj 487 000 HUF.\n" },
  limits: { subject_chars: 200, body_chars: 5000 }, ...over,
});

function show(data: LetterData) {
  const step = (title: string, uses: string): CaseView["steps"][string] => ({ title, uses, start: "auto", state: "running", phase: null,
    waiting_for: null, awaiting_start: false, note: null, result: null, actions: [] });
  const page: CaseView = {
    case: { id: CASE, pack: "insurance_offer", version: "1.5.0", title: "Insurance quote", name: "Minta Kft.", status: "open" },
    steps: { letter: step("Covering letter", "letter@1"), document: step("Offer document", "priced_document@1") },
    tabs: [{ id: "decision", label: "Decision and release", elements: [{ type: "letter", step: "letter", data }] }], next: null,
  };
  render(<>{elementOf("letter")!.render({ caseId: CASE, element: page.tabs[0].elements[0], page, onChanged: () => {} })}</>);
}

describe("a covering letter", () => {
  it("is accepted as the person changed it, with the page's document version", async () => {
    const act = vi.spyOn(api, "caseStepAction").mockResolvedValue({} as CaseView);
    show(waiting());
    const text = await screen.findByRole("textbox", { name: "The letter's text" });
    expect((screen.getByRole("textbox", { name: "Subject" }) as HTMLInputElement).value).toBe("Biztosítási ajánlat – Minta Kft.");
    expect(screen.getByText("To accept").className).toBe("status s-review");
    fireEvent.change(text, { target: { value: "Tisztelt Minta Anna!\n\nKöszönjük.\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Accept the letter" }));
    await waitFor(() => expect(act).toHaveBeenCalledWith(CASE, "letter", "accept", undefined,
      { to: "anna@minta.hu", subject: "Biztosítási ajánlat – Minta Kft.", body: "Tisztelt Minta Anna!\n\nKöszönjük.\n",
        expected_basis: { document: 1 } }));
  });

  it("is not accepted with a marker left in it or an address that is none", async () => {
    show(waiting());
    const text = await screen.findByRole("textbox", { name: "The letter's text" });
    fireEvent.change(text, { target: { value: "Tisztelt {{contact_name}}!" } });
    expect(screen.getByText("A marker is left in the letter: {{contact_name}}")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Accept the letter" })).toHaveProperty("disabled", true);
    fireEvent.change(text, { target: { value: "Tisztelt Minta Anna!" } });
    fireEvent.change(screen.getByRole("textbox", { name: "To" }), { target: { value: "anna.minta.hu" } });
    expect(screen.getByText("This is not an email address.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Accept the letter" })).toHaveProperty("disabled", true);
  });

  it("shows the accepted letter with its email file", async () => {
    show(waiting({ waits: false, approval: { ...missing, state: "approved" }, accepted: {
      version: 4, to: "anna@minta.hu", subject: "Biztosítási ajánlat – Minta Kft.", body: "Tisztelt Minta Anna!\n", by: "Minta Anna",
      at: "2026-10-27T09:00:00+00:00", document, file: { name: "ajanlat-kiserolevel-Minta-Kft-v4.eml", sha256: SHA } } }));
    const link = await screen.findByRole("link", { name: "ajanlat-kiserolevel-Minta-Kft-v4.eml" });
    expect(link.getAttribute("href")).toBe(`/api/cases/${CASE}/steps/letter/file`);
    expect(screen.getByText("Accepted").className).toBe("status s-done");
    expect(screen.queryByRole("button", { name: "Accept the letter" })).toBeNull();
  });
});
