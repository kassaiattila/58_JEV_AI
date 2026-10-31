// 264 (plan E, F5; the owner's decision of 2026-10-31): the data points table holds every field's value in one column;
// each row says its field's kind, so an amount reads as an amount ("1 767 500,00", not "1767500") and a text as it is.
// Synthetic rows.
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type DsColumn, type DsPage } from "../api";
import { DataTable } from "./DataTable";

afterEach(() => vi.restoreAllMocks());

const COLS: DsColumn[] = [
  { key: "field", label: "Field", kind: "enum", hidden: false, labels: null },
  { key: "value", label: "Value", kind: "text", hidden: false, labels: null, kind_from: "_kind" },
];

function page(): DsPage {
  const rows = [
    { _key: "a:gross_total", field: "gross_total", value: "1767500", _kind: "money" },
    { _key: "a:supplier_tax_id", field: "supplier_tax_id", value: "12345678", _kind: "text" },
  ];
  return { dataset: { name: "datapoints", label: "Data points", scope: ["run_id"], optional_scope: [] }, columns: COLS, rows,
    total: 2, matched: 2, offset: 0, limit: 100, facets: {} };
}

describe("a column whose rows say their kind", () => {
  it("shows an amount as an amount and a text as it is", async () => {
    vi.spyOn(api, "datasetQuery").mockImplementation(async () => page());
    render(<DataTable dataset="datapoints" scope={{ run_id: "run-1" }} label="Data points" />);
    expect(await screen.findByText(/^1\s767\s500[.,]00$/)).toBeTruthy();
    expect(screen.getByText("12345678")).toBeTruthy();
  });
});
