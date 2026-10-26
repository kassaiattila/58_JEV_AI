// 231 (stage D, D-f7): the document a step printed: the stored file with its download and fingerprint, the version it
// printed from which step; until then what it waits for; a step that could not print it says so. Invented data.
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import type { CaseView, DocumentViewData } from "../api";
import { setLanguage } from "../i18n";
import { documentStatus } from "./caseStatus";
import { elementOf } from "./registry";

beforeEach(async () => { await setLanguage("en"); });

const CASE = "wp-0000000d0f70";
const waiting: DocumentViewData = { state: "waiting", from_step: "premium", output: "rated_offer", version: null, file: null };

function show(data: DocumentViewData) {
  const step = (title: string, uses: string): CaseView["steps"][string] => ({ title, uses, start: "auto", state: "done", phase: null,
    waiting_for: null, awaiting_start: false, note: null, result: null, actions: [] });
  const page: CaseView = {
    case: { id: CASE, pack: "insurance_offer", version: "1.4.0", title: "Insurance quote", name: "Minta Kft.", status: "open" },
    steps: { document: step("Offer document", "priced_document@1"), premium: step("Premium decision", "decision@1") },
    tabs: [{ id: "decision", label: "Decision and release", elements: [{ type: "document_view", step: "document", data }] }], next: null,
  };
  render(<>{elementOf("document_view")!.render({ caseId: CASE, element: page.tabs[0].elements[0], page, onChanged: () => {} })}</>);
}

describe("a printed document", () => {
  it("links the stored file and names the version it printed, with its fingerprint", async () => {
    const sha = "ab12cd34ef56".padEnd(64, "0");
    show({ ...waiting, state: "done", version: 3, file: { name: "biztositasi-ajanlat-Minta-Kft-v3.docx", sha256: sha } });
    const link = await screen.findByRole("link", { name: "biztositasi-ajanlat-Minta-Kft-v3.docx" });
    expect(link.getAttribute("href")).toBe(`/api/cases/${CASE}/steps/document/file`);
    expect(screen.getByText("version 3 of “Premium decision”")).toBeTruthy();
    expect(screen.getByTitle(sha).textContent).toBe("ab12cd34ef56");
    expect(screen.getByText("Version 3").className).toBe("status s-done");
  });

  it("says what it waits for, and a step that could not print it", async () => {
    show(waiting);
    expect(await screen.findByText("Printed once “Premium decision” is approved.")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
    expect(documentStatus({ ...waiting, state: "failed" })).toEqual({ mark: "s-failed", text: "Not printed" });
  });
});
