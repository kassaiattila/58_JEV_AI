// 197 (plan 197 K0): a type's own name for a shared field. The quote request's customer is the requester; the utility
// bills' customer is the consumer, and since 190 they had shown the requester's name too. The review page names a
// field by the document's type; a page that does not know the type uses the shared name. Artificial data, no service.
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it } from "vitest";
import { setActor, type ItemResult } from "./api";
import { setLanguage } from "./i18n";
import { fieldLabel } from "./labels";
import { resetDrafts } from "./review/drafts";
import { FieldPanel } from "./review/FieldPanel";
import { quoteFieldLabel } from "./domains/quotes/quoteStatus";

function result(docType: string): ItemResult {
  return {
    run_id: "run-197", item_id: "b".repeat(64), kinds: { customer_name: "name" },
    extraction: { doc_type: docType, arm: "G", datapoints: { customer_name: "Példa Kft." }, field_conf: {}, validation: [],
      review_reasons: [] },
    correction: { revision: 0, fields: {}, sources: {}, confirmed: {} },
    effective: { customer_name: "Példa Kft." }, open_reasons: [], earlier_open_reasons: [], provenance: {}, source: null,
  } as unknown as ItemResult;
}

function panel(res: ItemResult) {
  return (
    <FieldPanel result={res} fields={["customer_name"]} bandOf={() => "check"} activeField={null}
      onActivate={() => {}} selection={{ ids: [], text: "" }} onClearSelection={() => {}} selectMode={false} onSaved={() => {}}
      onResolved={() => {}} onChooseAlternative={() => {}} readOnly={false} hasWords={false} />
  );
}

beforeEach(async () => { await act(() => setLanguage("hu")); setActor("Teszt Elek"); });
afterEach(() => { resetDrafts(); setActor(""); });

it("names a shared field by the document's type", () => {
  expect(fieldLabel("customer_name")).toBe("Felhasználó neve");
  expect(fieldLabel("customer_name", "viz_szamla")).toBe("Felhasználó neve");
  expect(fieldLabel("customer_name", "quote_request")).toBe("Ajánlatkérő neve");
  expect(fieldLabel("contact_name", "quote_request")).toBe("Kapcsolattartó");
  expect(quoteFieldLabel("customer_name")).toBe("Ajánlatkérő neve");
});

it("the review page of a utility bill shows the consumer, of a quote request the requester", () => {
  const bill = render(panel(result("viz_szamla")));
  expect(screen.getByText("Felhasználó neve")).toBeTruthy();
  expect(screen.queryByText("Ajánlatkérő neve")).toBeNull();
  bill.unmount();
  render(panel(result("quote_request")));
  expect(screen.getByText("Ajánlatkérő neve")).toBeTruthy();
});

it("the requester's name has its English name too", async () => {
  await act(() => setLanguage("en"));
  expect(fieldLabel("customer_name", "quote_request")).toBe("Requesting customer");
  expect(fieldLabel("customer_name", "viz_szamla")).toBe("Customer name");
});
