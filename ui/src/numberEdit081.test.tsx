// 081 (number reading, the owner's decisions of 2026-10-01): an amount or a quantity is edited the Hungarian way. The
// stored value ("35.56") shows with a decimal comma ("35,56"), the local service reads what is typed ("28.000" is
// 28 000) and refuses an ambiguous form; the saved value is read back in the message. Artificial data, no service.
import { describe, expect, it } from "vitest";
import type { ListColumn } from "./api";
import { editNumber, reasonText, savedNumbers } from "./labels";
import { buildSave } from "./review/FieldPanel";
import { fromRows, toRows } from "./review/ListTable";

describe("081 number editing", () => {
  it("shows a stored amount with a decimal comma and without grouping", () => {
    expect(editNumber("35.56")).toBe("35,56");
    expect(editNumber("28000")).toBe("28000");
    expect(editNumber("-1234.5")).toBe("-1234,5");
    expect(editNumber(1.153)).toBe("1,153");
    expect(editNumber(null)).toBe("");
  });

  it("does not save an unchanged amount typed in the editing form as a correction", () => {
    const draft = { baseRevision: 0, values: { gross_total: "35,56", net_total: "28000" }, sources: {}, lists: {} };
    const body = buildSave({ gross_total: "35.56", net_total: "28" }, { revision: 0, fields: {}, sources: {} } as never, draft as never, {},
      { gross_total: "money", net_total: "money" });
    expect(body.fields).toEqual({ net_total: "28000" });
  });

  it("shows the numeric cells of a line-item list in the editing form", () => {
    const cols: ListColumn[] = [{ name: "description", kind: "text" }, { name: "quantity", kind: "number" }, { name: "net_amount", kind: "money" }] as ListColumn[];
    const rows = toRows([{ description: "Áram", quantity: "1.153", net_amount: "3909.5" }], cols);
    expect(rows).toEqual([{ description: "Áram", quantity: "1,153", net_amount: "3909,5" }]);
    expect(fromRows(rows, cols)).toEqual([{ description: "Áram", quantity: "1,153", net_amount: "3909,5" }]);
  });

  it("names the saved amounts in the message", () => {
    const text = savedNumbers({ net_total: "28000", invoice_number: "A-1", gross_total: "35560.5" },
      { net_total: "money", gross_total: "money", invoice_number: "invoice_number" });
    expect(text.replace(/[  ]/g, " ")).toBe("Nettó összeg: 28 000; Bruttó összeg: 35 560,5");
  });

  it("explains the safety net's to-do in a sentence", () => {
    expect(reasonText("money:token_cut:net_total:'28,00'")).toBe("A kiválasztott érték csak egy része az iraton nyomtatott számnak: Nettó összeg");
  });
});
