// The UI's behavioural guarantees (040 K3 + 045 K3b), with lessons taken over from V4:
//  - the working copy survives a network error and a conflict, and an item switch too; no blind save on a conflict;
//  - a vanished package is not replaced by opening another; a slow old response does not overwrite the new selection;
//  - on the image: cycling through the fields under a point, word selection by rectangle, confidence bands,
//    sources to save;
//  - line list (048): a separate tab, cell editing, row deletion, the faulty row highlighted, saving the whole list.
import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, setActor, type ItemResult, type Provenance, type SourceWord, type UtilityReport } from "./api";
import { useLoad } from "./hooks";
import { checkText, intentLabel, itemName, nextFlowText, paramsText, reasonText } from "./labels";
import { EmailReview, splitLinks } from "./review/EmailReview";
import { PageViewer } from "./review/PageViewer";
import { bridgeErrorText, pullSummary, toggleAccount } from "./views/Mailbox";
import { draftKey, getDraft, resetDrafts, setField } from "./review/drafts";
import { buildSave, FieldPanel, rowOf } from "./review/FieldPanel";
import { ListTable } from "./review/ListTable";
import { bandOf, cyclePick, fieldsAtPoint, frameBoxes, orderFields, wordsInRect } from "./review/geometry";
import { parseRoute, routeHash } from "./route";
import { UtilityTable } from "./views/UtilityReport";

const RUN = "run-000000000001";
const ITEM = "a".repeat(64);

function result(over: Partial<ItemResult> = {}): ItemResult {
  return {
    run_id: RUN, item_id: ITEM,
    extraction: {
      doc_type: "invoice_hu", arm: "S", datapoints: { invoice_number: "MINTA-1", payment_iban: "HU00 1111" },
      field_conf: { invoice_number: 0.99, payment_iban: 0.58 }, validation: [], final_status: "needs_review", review_reasons: [],
    },
    correction: { run_id: RUN, item_id: ITEM, revision: 0, fields: {}, sources: {}, actor: null, note: null, created_at: null },
    effective: { invoice_number: "MINTA-1", payment_iban: "HU00 1111" },
    open_reasons: [], earlier_open_reasons: [],
    provenance: {
      invoice_number: { status: "located", method: "pick", page: 1, bbox: [0.1, 0.1, 0.3, 0.12], boxes: [[0.1, 0.1, 0.3, 0.12]], word_ids: [3], quote: "MINTA-1", alternatives: [], confidence: 0.99 },
      payment_iban: { status: "ambiguous", method: "search", alternatives: [], confidence: 0.58 },
    },
    source: { layer_id: "L", text_source: "pdf", pages: [{ page: 1, width_pt: 595, height_pt: 842 }] },
    ...over,
  };
}

function panel(res: ItemResult) {
  return (
    <FieldPanel result={res} fields={["invoice_number", "payment_iban"]} bandOf={() => "check"} activeField="invoice_number"
      onActivate={() => {}} selection={{ ids: [], text: "" }} onClearSelection={() => {}} selectMode={false}
      onSaved={() => {}} onResolved={() => {}} onChooseAlternative={() => {}} readOnly={false} hasWords />
  );
}

afterEach(() => { resetDrafts(); vi.restoreAllMocks(); });

describe("javítás mentése (munkapéldány)", () => {
  beforeEach(() => setActor("Teszt Elek"));
  afterEach(() => setActor(""));

  it("név nélkül nem küld mentést, hanem megmondja, mi hiányzik; a beírt érték megmarad", async () => {
    setActor("");
    const spy = vi.spyOn(api, "saveCorrection");
    render(panel(result()));
    const input = screen.getByLabelText("Számlaszám");
    await userEvent.clear(input);
    await userEvent.type(input, "MINTA-2");
    await userEvent.click(screen.getByRole("button", { name: /Javítás mentése/ }));
    expect(await screen.findByText(/Ki dolgozik\?/)).toBeTruthy();
    expect(spy).not.toHaveBeenCalled();
    expect((screen.getByLabelText("Számlaszám") as HTMLInputElement).value).toBe("MINTA-2");
  });

  it("hálózati hiba után a beírt érték megmarad, és újra menthető", async () => {
    const spy = vi.spyOn(api, "saveCorrection").mockRejectedValueOnce(new ApiError(0, "offline", "nem érhető el")).mockResolvedValueOnce(result());
    render(panel(result()));
    const input = screen.getByLabelText("Számlaszám");
    await userEvent.clear(input);
    await userEvent.type(input, "MINTA-1/A");
    await userEvent.click(screen.getByRole("button", { name: /Javítás mentése/ }));
    expect(await screen.findByText(/Nem sikerült menteni.*megmaradtak/)).toBeTruthy();
    expect((screen.getByLabelText("Számlaszám") as HTMLInputElement).value).toBe("MINTA-1/A");
    fireEvent.keyDown(window, { key: "Enter", ctrlKey: true }); // Ctrl+Enter saves too
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    expect(spy.mock.calls[1][2]).toEqual({ fields: { invoice_number: "MINTA-1/A" }, expected_revision: 0 });
    expect(await screen.findByText("Mentve.")).toBeTruthy();
  });

  it("a munkapéldány tételváltáskor megmarad; ha közben újabb verzió lett, nincs vak mentés", async () => {
    const key = draftKey(RUN, ITEM);
    setField(key, 0, "invoice_number", "X-2");
    const spy = vi.spyOn(api, "saveCorrection");
    const { unmount } = render(panel(result()));
    unmount(); // we moved to another item
    const newer = result({ correction: { ...result().correction, revision: 1, fields: { payment_iban: "HU99" }, actor: "más" } });
    render(panel(newer));
    expect((screen.getByLabelText("Számlaszám") as HTMLInputElement).value).toBe("X-2");
    expect(screen.getByRole("alert").textContent).toMatch(/újabb javítás/);
    expect((screen.getByRole("button", { name: /Javítás mentése/ }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: "Alkalmazás az új verzióra" }));
    expect(getDraft(key)?.baseRevision).toBe(1);
    expect(spy).not.toHaveBeenCalled();
  });

  it("a mentett halmaz: korábbi javítások és források + a munkapéldány; üres = nincs érték", () => {
    const prev = { ...result().correction, fields: { b: "20", c: "x" }, sources: { b: [4], c: [9] } };
    const out = buildSave({ a: "1", b: "2", c: "3" }, prev, { baseRevision: 0, values: { a: "10", c: "" }, sources: { a: [1, 2] } });
    expect(out).toEqual({ fields: { a: "10", b: "20", c: null }, sources: { a: [1, 2], b: [4] } });
    const back = buildSave({ b: "2" }, { ...prev, fields: { b: "20" }, sources: {} }, { baseRevision: 0, values: { b: "2" }, sources: {} });
    expect(back).toEqual({ fields: {}, sources: {} }); // reverted to the machine value
  });
});

describe("a képen", () => {
  const prov: Record<string, Provenance> = {
    a: { status: "located", method: "pick", page: 1, bbox: [0.1, 0.1, 0.4, 0.2], boxes: [[0.1, 0.1, 0.4, 0.2]], alternatives: [] },
    b: { status: "located", method: "pick", page: 1, bbox: [0.3, 0.15, 0.5, 0.2], boxes: [[0.3, 0.15, 0.5, 0.2]], alternatives: [] },
    c: { status: "ambiguous", method: "search", alternatives: [] },
    d: { status: "approximate", method: "pick_line", page: 1, bbox: [0.1, 0.5, 0.6, 0.52], boxes: [[0.1, 0.5, 0.6, 0.52]], alternatives: [] },
  };

  it("a közelítő (sor-szintű) keret is kattintható és keretezhető", () => {
    expect(fieldsAtPoint(prov, 1, 0.3, 0.51)).toEqual(["d"]);
    expect(frameBoxes(prov.d)).toEqual([[0.1, 0.5, 0.6, 0.52]]);
    expect(frameBoxes(prov.c)).toEqual([]);
  });

  it("a pont alatti mezők között ismételt kattintás lépked", () => {
    const hits = fieldsAtPoint(prov, 1, 0.35, 0.17);
    expect(hits).toEqual(["a", "b"]);
    expect(cyclePick(hits, null)).toBe("a");
    expect(cyclePick(hits, "a")).toBe("b");
    expect(cyclePick(hits, "b")).toBe("a");
    expect(fieldsAtPoint(prov, 2, 0.35, 0.17)).toEqual([]);
  });

  it("téglalappal a közepükkel beleeső szavak jelölődnek ki, olvasási sorrendben", () => {
    const words: SourceWord[] = [
      { id: 2, page: 1, line_no: 1, text: "880", x0: 0.3, y0: 0.1, x1: 0.34, y1: 0.12 },
      { id: 1, page: 1, line_no: 1, text: "071", x0: 0.25, y0: 0.1, x1: 0.29, y1: 0.12 },
      { id: 3, page: 1, line_no: 1, text: "Ft", x0: 0.6, y0: 0.1, x1: 0.62, y1: 0.12 },
    ];
    expect(wordsInRect(words, 1, { x: 0.35, y: 0.13 }, { x: 0.24, y: 0.09 }).map((w) => w.id)).toEqual([1, 2]);
  });

  it("bizonyosság-sávok (a V4 határai) és mezősorrend (teendő, gyenge becslés, alap)", () => {
    const bands = { confident: 0.9, check: 0.5 };
    expect([0.95, 0.9, 0.6, 0.2, null].map((c) => bandOf(c, bands))).toEqual(["confident", "confident", "check", "likely_wrong", "unknown"]);
    expect(bandOf(0.99, bands, true)).toBe("check"); // corrected field: the estimate referred to the machine value
    const band = (f: string) => (f === "c" ? "likely_wrong" : "confident");
    expect(orderFields(["a", "b", "c", "d"], new Set(["d"]), band)).toEqual(["d", "c", "a", "b"]);
  });
});

describe("kiválasztott csomag identitása", () => {
  it("a címben lévő azonosító marad a kiválasztás, nincs visszaesés az első elemre", () => {
    const r = parseRoute("#/workpackages/wp-000000000009/review/" + "b".repeat(64));
    expect(r).toEqual({ view: "workpackages", wpId: "wp-000000000009", stage: "review", itemId: "b".repeat(64) });
    expect(routeHash(r)).toBe("#/workpackages/wp-000000000009/review/" + "b".repeat(64));
    // unknown section: the package opens at its next step (without a stage), not another package
    expect(parseRoute("#/workpackages/wp-1/ismeretlen")).toEqual({ view: "workpackages", wpId: "wp-1", stage: undefined });
    expect(parseRoute("")).toEqual({ view: "workpackages" });
  });

  it("kulcsváltáskor a régi, később érkező válasz nem írja felül az újat", async () => {
    let resolveOld: (v: string) => void = () => {};
    const old = new Promise<string>((r) => { resolveOld = r; });
    const fns: Record<string, () => Promise<string>> = { "wp:A": () => old, "wp:B": () => Promise.resolve("B adatai") };
    const { result: hook, rerender } = renderHook(({ k }) => useLoad(k, fns[k]), { initialProps: { k: "wp:A" } });
    rerender({ k: "wp:B" });
    await waitFor(() => expect(hook.current.data).toBe("B adatai"));
    await act(async () => { resolveOld("A adatai"); await old; });
    expect(hook.current.data).toBe("B adatai");
  });
});

describe("teendő-szövegek", () => {
  it("az okkód hétköznapi mondat lesz, ismeretlen kód változatlan", () => {
    expect(reasonText("pick:low_conf:payment_iban:0.58")).toBe("Bizonytalan érték: Bankszámlaszám (valószínűség 0,58)");
    expect(reasonText("ocr:partial_pages:12/13")).toBe("Nem minden oldal lett felismerve (12/13)");
    expect(reasonText("valami:uj")).toBe("valami:uj");
    // 065: the broad category of the detection also has a Hungarian name (until now „other” was shown)
    expect(reasonText("detect:detail_open:other")).toBe("A részletes típus nem dönthető el (kategória: Egyéb irat); válaszd ki kézzel");
    expect(reasonText("validator:balance.discontinuity")).toBe("A futó egyenleg megszakad");
    expect(reasonText("validator:taxid.unrecognized")).toBe("Az adószám alakja nem ismerhető fel"); // 069
    // 069: the to-do for a field that is on the document but has no candidate, and for a document without a type pack
    expect(reasonText("pick:present_no_candidates:payment_iban:0.93")).toBe("Az iraton van, de a kód nem talált hozzá jelöltet: Bankszámlaszám (0,93)");
    expect(reasonText("detect:no_type_pack:payment_reminder")).toMatch(/^Ehhez az irattípushoz nincs adatkinyerés \(.+\); nézd meg kézzel$/);
  });

  it("058: kódnév helyett magyar név — szándék, recept-paraméterek", () => {
    expect(reasonText("intent:low_conf:newsletter_marketing:0.49")).toBe("Bizonytalan levél-szándék: Hírlevél / Marketing (0,49)");
    expect(intentLabel("ismeretlen_kulcs")).toBe("ismeretlen_kulcs");
    // 080: the path by what it does (the owner's decision of 2026-10-01)
    expect(paramsText({ arm: "S", jev_cache: "live" })).toBe("Út: JEV, ahol lehet — olcsóbb, tételsorok nélkül; máshol GPT (S) · Korábbi válaszok: mindig élő hívás");
  });
});

describe("tételes lista (048)", () => {
  const COLS = [{ name: "direction", kind: "text", options: ["debit", "credit"] }, { name: "amount", kind: "money" }, { name: "memo", kind: "text" }];
  const TXS = [{ direction: "credit", amount: "200", memo: null }, { direction: "debit", amount: "500", memo: "díj" }];

  function statement(over: Partial<ItemResult> = {}): ItemResult {
    const base = result();
    return {
      ...base,
      extraction: { ...base.extraction!, doc_type: "statement_cib", datapoints: { opening_balance: "1000", transactions: TXS } },
      effective: { opening_balance: "1000", transactions: TXS },
      provenance: {},
      lists: { transactions: { columns: COLS } },
      checks: [{ name: "running_balance_check", ok: false, code: "balance.discontinuity", detail: "line 2: expected 1150.00, computed 700.00", rows: { transactions: [2] } }],
      ...over,
    };
  }

  function listPanel(res: ItemResult) {
    const Wrapper = () => {
      const [tab, setTab] = useState("fields");
      return (
        <FieldPanel result={res} fields={["opening_balance"]} bandOf={() => "check"} activeField={null} onActivate={() => {}}
          selection={{ ids: [], text: "" }} onClearSelection={() => {}} selectMode={false}
          onSaved={() => {}} onResolved={() => {}} onChooseAlternative={() => {}} readOnly={false} hasWords tab={tab} onTab={setTab} />
      );
    };
    return <Wrapper />;
  }

  beforeEach(() => setActor("Teszt Elek"));
  afterEach(() => setActor(""));

  it("a mentett halmaz: változatlan lista kimarad; változott lista teljes egészében megy, üres cella = nincs érték", () => {
    const prev = result().correction;
    const lists = { transactions: { columns: COLS } };
    const same = buildSave({ transactions: TXS }, prev, { baseRevision: 0, values: {}, sources: {}, lists: {
      transactions: [{ direction: "credit", amount: "200", memo: "" }, { direction: "debit", amount: "500", memo: "díj" }] } }, lists);
    expect(same.fields).toEqual({});
    const changed = buildSave({ transactions: TXS }, prev, { baseRevision: 0, values: {}, sources: {}, lists: {
      transactions: [{ direction: "debit", amount: "50", memo: " " }, { direction: "", amount: "", memo: "" }] } }, lists);
    expect(changed.fields).toEqual({ transactions: [{ direction: "debit", amount: "50", memo: null }] }); // the empty row is left out
    const kept = buildSave({ transactions: TXS }, { ...prev, fields: { transactions: [TXS[0]] } }, undefined, lists);
    expect(kept.fields).toEqual({ transactions: [TXS[0]] }); // the earlier list correction is kept
  });

  it("külön fülön látszik, a hibás sor kiemelve, cella javítható, sor törölhető, a teljes lista mentődik", async () => {
    const spy = vi.spyOn(api, "saveCorrection").mockResolvedValue(statement());
    render(listPanel(statement()));
    expect(screen.getByText(/futó egyenleg megszakad: 2\. sor/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "2. sor" })); // the check leads to the faulty row
    expect(screen.getByRole("tab", { name: /Tranzakciók \(2\)/ }).getAttribute("aria-selected")).toBe("true");
    const amount = screen.getByLabelText("2. sor: Összeg") as HTMLInputElement;
    expect(amount.closest("tr")?.className).toBe("row-bad");
    await userEvent.clear(amount);
    await userEvent.type(amount, "50");
    await userEvent.click(screen.getByRole("button", { name: "1. sor törlése" }));
    expect(screen.getByRole("tab", { name: /Tranzakciók \(1\) •/ })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /Javítás mentése/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    expect(spy.mock.calls[0][2]).toEqual({ fields: { transactions: [{ direction: "debit", amount: "50", memo: "díj" }] }, expected_revision: 0 });
  });

  it("az ellenőrzés eredménye hétköznapi mondat, a sorral és az értékekkel", () => {
    expect(checkText("balance.discontinuity", "line 2: expected 1150.00, computed 700.00"))
      .toBe("A futó egyenleg megszakad: 2. sor (a kivonaton 1150,00, számolva 700,00)");
    expect(checkText("closing.mismatch", "open+S-close=10.00")).toBe("A nyitó egyenleg + tranzakciók nem adják ki a záró egyenleget");
  });

  it("a tétel-ellenőrzés minden hibás sort és az összeg-eltérést megnevezi (053 T3)", () => {
    expect(checkText("lines.arithmetic_mismatch", "line 2: qty*price=300.00 vs 350; line 5: net*(1+vat)=127.00 vs 150"))
      .toBe("Tételsoron a mennyiség × egységár vagy a nettó + ÁFA nem adja ki a sor összegét (2., 5. sor)");
    expect(checkText("lines.total_mismatch", "net: sum-total=-100.5"))
      .toBe("A tételek összege nem egyezik a számla végösszegével (nettó: eltérés -100,5)");
  });
});

describe("postafiók és levél-tétel (048 T2)", () => {
  it("a postafiók útvonala és a letöltés összefoglalója", () => {
    expect(parseRoute("#/mailbox")).toEqual({ view: "settings", section: "mailboxes" }); // 057: the old address leads to Settings
    expect(routeHash({ view: "settings", section: "mailboxes" })).toBe("#/settings/mailboxes");
    expect(pullSummary({ status: "ok", result: { new: 3, changed: 1, duplicate: 2, workpackage: "wp-1" } })).toBe("4 új levél (1 megváltozott) · 2 már megvolt");
    // 073: the known script error is shown in the UI language here too (until 072 the raw English text)
    expect(pullSummary({ status: "error", result: { error: "Outlook must already be running." } })).toBe("Az Outlook nem fut ezen a gépen. Indítsd el, és próbáld újra.");
    expect(bridgeErrorText("Outlook must already be running in the current interactive session.")).toBe("Az Outlook nem fut ezen a gépen. Indítsd el, és próbáld újra.");
    // 065: a „Korábban használt” (Previously used) address adds / removes, it does not replace
    expect(toggleAccount("a@x.hu", "b@y.hu")).toBe("a@x.hu, b@y.hu");
    expect(toggleAccount("a@x.hu, b@y.hu", "a@x.hu")).toBe("b@y.hu");
    expect(toggleAccount("", "a@x.hu")).toBe("a@x.hu");
    expect(nextFlowText("human:fetch_document")).toBe("Kézi: a számla feldolgozása");
    expect(nextFlowText("m2:invoice_hu")).toBe("Adatkinyerés a csatolmányból (Magyar számla)"); // 058: the type's name
    expect(itemName({ item_id: "x", source_path: "C:\\inbox\\a\\message.json" }, { x: "Számla — Kft." })).toBe("Számla — Kft.");
  });

  it("a levél-tétel: a levél, a felismert szándék és a teendő rendezése", async () => {
    const spy = vi.spyOn(api, "resolveReason").mockResolvedValue({ status: "resolved" });
    const onChanged = vi.fn();
    const base = result();
    const mail: ItemResult = {
      ...base, kind: "email", extraction: null, source: null, provenance: {},
      open_reasons: [{ id: 7, reason: "intent:low_conf:szamlakuldes:0.61" } as ItemResult["open_reasons"][number]],
      email: { subject: "Szeptemberi számla", sender: "szamla@minta.hu", sender_name: "Minta Kft.", to: ["iroda@minta.hu"],
        received_at: "2026-09-27T10:00:00", mailbox: "iroda@minta.hu", body: "Mellékelten küldjük.", attachments: ["szamla.pdf"],
        result: { intent: "szamlakuldes", intent_label: "Számlaküldés", confidence: 0.61, next_flow: "human:low_confidence",
          attachments: [{ filename: "szamla.pdf", doc_type: "invoice" }], from_this_run: true, signals: {} } },
    };
    render(<EmailReview data={mail} onChanged={onChanged} />);
    expect(screen.getByText("Szeptemberi számla")).toBeTruthy();
    expect(document.querySelector(".intent")?.textContent).toBe("Számlaküldés"); // the correcting picker shows this too
    expect(screen.getByText("Kézi ellenőrzés: bizonytalan szándék")).toBeTruthy();
    expect(screen.getByText("Bizonytalan levél-szándék: Számlaküldés (0,61)")).toBeTruthy(); // 058: the intent's name, not its code
    await userEvent.click(screen.getByRole("button", { name: "Rendezve" }));
    expect(spy).toHaveBeenCalledWith(7);
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("058 K5.1: a szándék kézzel javítható; a levágott szöveg jelölve", async () => {
    const save = vi.spyOn(api, "saveCorrection").mockResolvedValue(result());
    const onChanged = vi.fn();
    const base = result();
    const mail: ItemResult = {
      ...base, kind: "email", extraction: null, source: null, provenance: {}, open_reasons: [],
      email: { subject: "Hírlevél", sender: "hir@minta.hu", sender_name: null, to: [], received_at: null, mailbox: null,
        body: "Szöveg", attachments: [],
        body_coverage: { status: "shortened", chars: 9000, own_chars: 8000, seen_chars: 4000, seen_lines: 60, quoted_removed: false },
        result: { intent: "newsletter_marketing", intent_label: "Hírlevél / Marketing", confidence: 0.49, next_flow: "human:low_confidence",
          attachments: [], from_this_run: true, signals: {} } },
    };
    render(<EmailReview data={mail} onChanged={onChanged} />);
    expect(screen.getByText(/csak az elejét látta: 4000 \/ 8000 karakter/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /Szándék javítása/ }));
    await userEvent.click(screen.getByRole("option", { name: /Üzleti levelezés/ }));
    await userEvent.click(screen.getByRole("button", { name: "Javítás mentése" }));
    expect(save).toHaveBeenCalledWith(RUN, ITEM, { fields: { intent: "business_correspondence" }, expected_revision: 0 });
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("058 K5.2: a levél iratként futott csatolmánya a saját eredményére visz", () => {
    const base = result();
    const mail: ItemResult = {
      ...base, kind: "email", extraction: null, source: null, provenance: {}, open_reasons: [],
      attachment_items: [{ item_id: "b".repeat(64), filename: "szamla.pdf" }],
      email: { subject: "Számla", sender: null, sender_name: null, to: [], received_at: null, mailbox: null, body: "", attachments: ["szamla.pdf"],
        result: { intent: "szamlakuldes", intent_label: null, confidence: 0.9, next_flow: "m2:invoice_hu",
          attachments: [{ filename: "szamla.pdf", doc_type: "invoice_hu" }], from_this_run: true, signals: {} } },
    };
    render(<EmailReview data={mail} wpId="wp-000000000001" onChanged={() => {}} />);
    expect(screen.getByText("szamla.pdf: Magyar számla")).toBeTruthy();
    const link = screen.getByRole("link", { name: /szamla\.pdf: az adatkinyerés eredménye/ });
    expect(link.getAttribute("href")).toBe(`#/workpackages/wp-000000000001/review/${"b".repeat(64)}`);
  });

  it("058 K5.3: a feladatjavaslatot csak ember fogadja el; a kiesett javaslatok száma látszik", async () => {
    const decide = vi.spyOn(api, "decideTask").mockResolvedValue(result());
    const onChanged = vi.fn();
    const base = result();
    const mail: ItemResult = {
      ...base, kind: "email", extraction: null, source: null, provenance: {}, open_reasons: [],
      email: { subject: "Kérdés", sender: null, sender_name: null, to: [], received_at: null, mailbox: null, body: "Mikor érkezik a szerződés?",
        attachments: [], result: { intent: "business_correspondence", intent_label: null, confidence: 0.9, next_flow: "human:inbox",
          attachments: [], from_this_run: true, signals: {} },
        tasks: { status: "proposed", tasks: [{ index: 0, action: "reply", title: "Válasz a szerződés érkezéséről", due_date: null, assignee_hint: null,
          evidence: [{ pointer: "/messages/0/body", quote: "Mikor érkezik a szerződés?" }], decision: null }],
          rejected: [{ code: "task_evidence_failed", index: 1, details: ["field_value_not_in_source_quote"] }] } },
    };
    render(<EmailReview data={mail} onChanged={onChanged} />);
    expect(screen.getByText("Válasz a szerződés érkezéséről")).toBeTruthy();
    expect(screen.getByText(/Válasz egy kifejezett kérésre/)).toBeTruthy();
    expect(screen.getByText(/„Mikor érkezik a szerződés\?”/)).toBeTruthy();
    expect(screen.getByText(/1 javaslat kiesett a bizonyíték-ellenőrzésen/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Elfogadás" }));
    expect(decide).toHaveBeenCalledWith(RUN, ITEM, 0, "accepted");
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("062: az összevont javaslat és a kiesett javaslat tartalma az elbukott résszel látszik", async () => {
    const base = result();
    const mail: ItemResult = {
      ...base, kind: "email", extraction: null, source: null, provenance: {}, open_reasons: [],
      email: { subject: "Számla", sender: null, sender_name: null, to: [], received_at: null, mailbox: null, body: "Szia Anna, várjuk a számládat.",
        attachments: [], result: { intent: "business_correspondence", intent_label: null, confidence: 0.9, next_flow: "human:inbox",
          attachments: [], from_this_run: true, signals: {} },
        tasks: { status: "proposed", tasks: [{ index: 0, action: "provide_document", title: "Számla beküldése", due_date: null, assignee_hint: null,
          evidence: [{ pointer: "/messages/0/body", quote: "várjuk a számládat" }], decision: null, merged: 1 }],
          rejected: [
            { code: "task_evidence_failed", index: 1, action: "provide_document", title: "Küldd a számlát", due_date: null, assignee_hint: "Anna",
              details: ["field_value_not_in_source_quote"], failed_parts: ["assignee"],
              quotes: [{ part: "evidence", pointer: "/messages/0/body", quote: "várjuk a számládat", ok: true },
                       { part: "assignee", pointer: "/messages/0/body", quote: "Kedves Anna!", ok: false }] },
            { code: "task_evidence_failed", index: 2, details: ["evidence_quote_mismatch"] }] } },
    };
    render(<EmailReview data={mail} onChanged={() => {}} />);
    expect(screen.getByText(/2 azonos javaslat összevonva/)).toBeTruthy();
    await userEvent.click(screen.getByText(/2 javaslat kiesett a bizonyíték-ellenőrzésen/));
    expect(screen.getByText("Küldd a számlát")).toBeTruthy();
    expect(screen.getByText(/Nem igazolható: a felelős/)).toBeTruthy();
    expect(screen.getByText(/„Kedves Anna!” – nem áll szó szerint a levélben/)).toBeTruthy();
    expect(screen.getByText(/„várjuk a számládat” – szó szerint megvan/)).toBeTruthy();
    expect(screen.getByText(/A javaslat szövege ennél a korábbi futásnál nem maradt meg/)).toBeTruthy();
  });

  it("058: a levél hosszú linkjei rövid, nem kattintható jelöléssé válnak", () => {
    const parts = splitLinks("Nézd meg: <https://link.minta.hu/ls/click?upn=u001.AAAA-2Fp> vagy https://www.pelda.hu/a?b=c\nKöszönjük");
    expect(parts).toEqual([
      { text: "Nézd meg: " }, { url: "https://link.minta.hu/ls/click?upn=u001.AAAA-2Fp", host: "link.minta.hu" },
      { text: " vagy " }, { url: "https://www.pelda.hu/a?b=c", host: "www.pelda.hu" }, { text: "\nKöszönjük" },
    ]);
    expect(splitLinks("nincs benne link")).toEqual([{ text: "nincs benne link" }]);
  });
});

describe("keretek a képen és tételsorok helye (053)", () => {
  const box = (y: number): Provenance => ({ status: "located", method: "search", alternatives: [], page: 1, bbox: [0.1, y, 0.3, y + 0.02] });

  it("minden megtalált keret látszik, a kiválasztott erősen; a lista[n] kulcs sorszámmá alakul", async () => {
    const prov = { supplier_name: box(0.1), invoice_number: box(0.2), due_date: { status: "ambiguous", method: "search", alternatives: [] } as Provenance };
    const { container } = render(<PageViewer pageUrl={() => "/p/1.png"} pages={[{ page: 1, width_pt: 600, height_pt: 800 }]} prov={prov}
      activeField="supplier_name" focusRequest={0} colorOf={() => "#008A2E"} labelOf={(f) => f} onPickField={() => {}}
      onChooseAlternative={() => {}} selectMode={false} words={null} selected={[]} onSelect={() => {}} />);
    fireEvent.load(screen.getByAltText("Az irat 1. oldala"));
    expect(container.querySelectorAll(".field-box.all").length).toBe(1); // the found field that is not selected
    expect(container.querySelectorAll(".field-box.active").length).toBe(1);
    expect(rowOf("line_items[3]", "line_items")).toBe(3);
    expect(rowOf("line_items[3]", "transactions")).toBeNull();
    expect(rowOf("supplier_name", "line_items")).toBeNull();
  });

  it("a tételsorra kattintva a sor kiválasztódik, az aktív sor kiemelve", async () => {
    const pick = vi.fn();
    const cols = [{ name: "description", kind: "text" }, { name: "net_amount", kind: "money" }];
    render(<ListTable field="line_items" columns={cols} rows={[{ description: "Alapdíj", net_amount: "261" }, { description: "Energiadíj", net_amount: "6551" }]}
      badRows={[]} focusRow={null} activeRow={2} onRowPick={pick} edited={false} corrected={false} readOnly={false} onChange={() => {}} onRevert={() => {}} />);
    const second = screen.getByLabelText("2. sor: Nettó") as HTMLInputElement;
    expect(second.closest("tr")?.className).toBe("row-active");
    await userEvent.click(screen.getByLabelText("1. sor: Leírás"));
    expect(pick).toHaveBeenCalledWith(1);
  });
});

describe("hosszú irat lapozása (048)", () => {
  it("szóréteg nélkül is az irat valódi oldalszámáig lapoz", async () => {
    render(<PageViewer pageUrl={(n) => `/p/${n}.png`} pages={[]} pageCount={9} prov={{}} activeField={null} focusRequest={0}
      colorOf={() => "#000"} labelOf={(f) => f} onPickField={() => {}} onChooseAlternative={() => {}} selectMode={false}
      words={null} selected={[]} onSelect={() => {}} />);
    expect(screen.getByText("1 / 9")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Következő oldal" }));
    expect(screen.getByText("2 / 9")).toBeTruthy();
    expect((screen.getByAltText("Az irat 2. oldala") as HTMLImageElement).getAttribute("src")).toBe("/p/2.png");
  });
});

describe("riportok (054 K4)", () => {
  it("a közmű-költség rács jelöli a hiányt és az átfedést, a cella a forrásaira visz", async () => {
    const src = { item_id: "a", file: "a.pdf", amount: "10000.00", page: 1, field: "gross_total", corrected: false, open_reasons: 0 };
    const rep: UtilityReport = {
      run_id: "run-1", months: ["2026-01", "2026-02", "2026-03"], grand_total: "22000.00", unplaced: [],
      duplicates: [{ item_id: "m2", file: "m2.pdf", doc_type: "mohu_szamla", same_as: "m1", same_as_file: "m1.pdf" }],
      series: [{ address: "1111 Budapest, Minta út 1", utility: "Villamos energia", summary_only: false, suppliers: ["MVM"], consumption_unit: "kWh",
        total: "22000.00", bills: 2, cells: {
          "2026-01": { status: "ok", amount: "10000.00", consumption: null, settlement: false, sources: [src] },
          "2026-02": { status: "missing", amount: null, consumption: null, settlement: false, sources: [] },
          "2026-03": { status: "overlap", amount: "12000.00", consumption: null, settlement: true, sources: [{ ...src, item_id: "b", amount: "12000.00" }] },
        } }],
    };
    const onCell = vi.fn();
    render(<UtilityTable rep={rep} onCell={onCell} />);
    expect(screen.getByRole("button", { name: /2026-02: hiányzik/ }).closest("td")?.className).toContain("cell-missing");
    expect(screen.getByRole("button", { name: /2026-03/ }).textContent).toContain("*"); // settlement invoice
    expect(screen.getByText(/m2\.pdf = m1\.pdf/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /2026-01/ }));
    expect(onCell.mock.calls[0][1]).toBe("2026-01");
    expect(parseRoute("#/reports/run-1")).toEqual({ view: "legacy-result", runId: "run-1", table: "utility" });
  });
});
