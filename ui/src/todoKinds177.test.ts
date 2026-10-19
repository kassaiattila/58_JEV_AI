// 177 (plan 170 E6): every to-do kind of the registry (configs/todo_kinds.json) gets a label, not its raw code; and a
// watched folder's package names its folder as such (the owner's decision of 2026-10-19).
import { describe, expect, it } from "vitest";
import registry from "../../configs/todo_kinds.json";
import type { Workpackage } from "./api";
import { reasonText } from "./labels";
import { createdFrom } from "./views/PackageItems";

describe("every to-do kind has a label (177)", () => {
  it("the registry lists the kinds", () => {
    expect(registry.kinds.length).toBeGreaterThan(80);
  });
  for (const kind of registry.kinds) {
    it(kind.code, () => {
      const text = reasonText(kind.example);
      expect(text).not.toBe(kind.example);
      // the label does not show the code itself (a family's code varies: its example is checked above)
      if (!kind.code.includes("*")) expect(text).not.toContain(kind.code.replace(/:$/, ""));
    });
  }
});

describe("the kinds that showed their raw code until 177", () => {
  it("the JEV verification's flags name the field and the probability", () => {
    expect(reasonText("jev:absence_wrong:invoice_number:0.85")).toBe("JEV szerint a mező üresen maradt, pedig szerepel az iraton: Számlaszám (0,85)");
    expect(reasonText("jev:off_target:net_total:0.81")).toBe("JEV szerint az érték egy másik mezőhöz tartozik: Nettó összeg (0,81)");
    expect(reasonText("jev:parties_swapped:0.88")).toBe("JEV szerint a szállító és a vevő fel van cserélve (0,88)");
    expect(reasonText("jev:line_items_missing_rows:0.74")).toBe("JEV szerint az iraton olyan tételsor is van, amely a kinyert listából hiányzik (0,74)");
  });
  it("a number that cannot be read names its list row and column", () => {
    expect(reasonText("line_items[3].gross_amount:unparseable:'12,5x'")).toMatch(/^Nem értelmezhető szám: .+, 4\. sor: .+$/);
    expect(reasonText("meter_reading_end:unparseable:'abc'")).toMatch(/^Nem értelmezhető szám: /);
    expect(reasonText("statement_type:not_in_enum:'Invented kind'")).toMatch(/^A mező értéke nincs a megengedett értékek között: /);
  });
  it("the suspicious email's own to-do", () => {
    expect(reasonText("signal:prompt_injection:1.00")).toBe("A levélben beszúrt utasítás lehet (1,00): olvasd el, mielőtt a levél alapján bármit teszel");
  });
});

describe("a package's origin (177)", () => {
  const wp = (source_kind: string, source_ref: string | null) => ({ source_kind, source_ref }) as Workpackage;
  it("a watched folder is named as a watched folder, not as a file", () => {
    expect(createdFrom(wp("watch", "C:\\mappa\\2022"))).toBe("a(z) C:\\mappa\\2022 figyelt mappa");
  });
  it("the other kinds as before", () => {
    expect(createdFrom(wp("folder", "C:\\mappa"))).toBe("C:\\mappa");
    expect(createdFrom(wp("mailbox", "a@b.hu"))).toBe("a@b.hu postafiók");
    expect(createdFrom(wp("manual", null))).toBe("kézzel választott fájlok");
    expect(createdFrom(wp("manual", "C:\\export\\kivonat.csv"))).toBe("a(z) kivonat.csv fájl");
  });
});
