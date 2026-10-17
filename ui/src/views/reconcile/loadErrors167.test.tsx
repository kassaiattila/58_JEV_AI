// 167 (review 160 U-11): a failed load in the reconciliation views says so instead of an empty pane or "Loading…" for
// ever. Artificial data, no service.
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, ApiError, type ReconcileLine } from "../../api";
import { setLanguage } from "../../i18n";
import { DocumentPair } from "./DocumentPair";

beforeEach(async () => { await setLanguage("en"); });
afterEach(async () => { vi.restoreAllMocks(); await setLanguage("hu"); });

it("the statement pane names a failed lookup of the line's place", async () => {
  vi.spyOn(api, "reconcileLocate").mockRejectedValue(new ApiError(503, "error", "the statement's file is locked"));
  const line = { id: "l-1", file: "bank.xlsx", currency: "HUF", account: "…1234", amount: "100.00", booked_on: "2026-06-01",
    memo: "", partner: "", direction: "out" } as unknown as ReconcileLine;
  render(<DocumentPair wpId="wp-1" line={line} invoice={null} opens={{}} />);
  expect(await screen.findByText("The line's place on the statement could not be looked up: the statement's file is locked")).toBeTruthy();
});
