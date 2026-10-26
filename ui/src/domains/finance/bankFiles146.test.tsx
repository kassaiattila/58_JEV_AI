// 146 (backlog D-bank-files): the bank files the system reads, from the service's catalogue, in Settings › Processing
// and folded on the new statement package's form; every text of the catalogue has its Hungarian translation.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import catalogue from "../../../../configs/bank_files.json";
import { api } from "../../api";
import type { BankFilesCatalogue } from "./api";
import hungarian from "../../i18n/hu-native.json";
import { setLanguage } from "../../i18n";
import { BankFilesInfo, BankFilesPanel } from "./BankFiles";

const CAT: BankFilesCatalogue = {
  version: "1.0.0", intro: catalogue.intro, read_by: catalogue.read_by, checks: catalogue.checks,
  not_read: catalogue.not_read,
  labels: { booking_date: "Könyvelés", amount: "Összeg", fee: "Díj", currency: "Pénznem", memo: "Közlemény" },
  files: [
    { id: "camt053", reader: { profile: "camt053" }, read_by: "code", bank: catalogue.files[3].bank, statement: catalogue.files[3].statement,
      formats: catalogue.files[3].formats, suffixes: [".xml"], kinds: ["bank_account"], version: "statement_tables 1.5.0",
      header: ["currency"], reads: ["booking_date", "amount", "fee"], not_read: ["memo"], checks: ["running_balance"],
      notes: catalogue.files[3].notes, described: true },
    { id: "statement_erste", reader: { type: "statement_erste" }, read_by: "ai", bank: null, statement: null, formats: [],
      suffixes: [".pdf"], kinds: ["bank_account", "credit_card"], version: "statement_erste 1.0.0", header: [],
      reads: ["booking_date"], not_read: ["fee"], checks: [], notes: [], described: false },
  ],
};

beforeEach(() => setLanguage("hu"));
afterEach(() => { cleanup(); vi.restoreAllMocks(); setLanguage("hu"); });

describe("the bank files the system reads", () => {
  it("shows each file's reader, facts, checks and notes, and what no reader knows, in Hungarian", async () => {
    vi.spyOn(api, "bankFiles").mockResolvedValue(CAT);
    render(<BankFilesPanel />);
    const card = await screen.findByRole("region", { name: "Bármely bank (az Erste tranzakciókódjait és kártyaadatait ismeri): A bank szabványos XML-kivonata (ISO 20022 camt.053)" });
    expect(card.textContent).toContain("Kódból olvasva, ingyenes");
    expect(card.textContent).toContain("Könyvelés, Összeg, Díj");
    expect(card.textContent).toContain("Nem olvassa");
    expect(card.textContent).toContain("Közlemény");
    expect(card.textContent).toContain("a tételenkénti egyenleg, soronként");
    expect(card.textContent).toContain("Nem kell hozzá PDF");
    expect(card.textContent).toContain("camt053 · statement_tables 1.5.0");
    const plain = screen.getByRole("region", { name: "statement_erste: statement_erste" });
    expect(plain.textContent).toContain("AI-val kinyerve, fizetős");
    expect(plain.textContent).toContain("Még nincs leírása");
    const none = screen.getByRole("region", { name: "Amit egyik olvasó sem ismer" });
    expect(none.textContent).toContain("OTP, K&H, Raiffeisen");
  });

  it("asks the service only when the folded list is opened", async () => {
    const call = vi.spyOn(api, "bankFiles").mockResolvedValue(CAT);
    const { container } = render(<BankFilesInfo />);
    expect(screen.getByText("Milyen banki állományokat tud olvasni a rendszer?")).toBeTruthy();
    expect(call).not.toHaveBeenCalled();
    const details = container.querySelector("details") as HTMLDetailsElement;
    details.open = true;
    fireEvent(details, new Event("toggle"));
    expect(await screen.findByText("Amit egyik olvasó sem ismer")).toBeTruthy();
    expect(call).toHaveBeenCalledTimes(1);
  });

  it("has a Hungarian translation for every text of the catalogue", () => {
    const texts = [catalogue.intro, ...Object.values(catalogue.read_by), ...Object.values(catalogue.checks), ...catalogue.not_read,
      ...catalogue.files.flatMap((f) => [f.bank, f.statement, ...f.formats, ...f.notes])];
    for (const text of texts) expect((hungarian as Record<string, string>)[text], text).toBeTruthy();
  });
});
