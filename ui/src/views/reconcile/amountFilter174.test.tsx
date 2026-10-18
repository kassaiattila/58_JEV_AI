// 174 (review 160 M-17): an amount the filter cannot read did nothing without a word. The field says it is unreadable
// and that it does not filter; a readable one says nothing. Synthetic values only.
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setLanguage } from "../../i18n";
import { NO_LINE_FILTERS } from "./filters";
import { LineFilterRow } from "./FilterRows";

beforeEach(async () => { await setLanguage("en"); });

describe("174 M-17 an unreadable amount in the filter", () => {
  it("is marked and named, and does not filter", () => {
    render(<LineFilterRow lines={[]} value={{ ...NO_LINE_FILTERS, min: "12,5x" }} onChange={vi.fn()} />);
    expect(screen.getByLabelText("Amount from").getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByLabelText("Amount to").getAttribute("aria-invalid")).toBeNull();
    expect(screen.getByText("An amount cannot be read, so it does not filter.")).toBeTruthy();
  });

  it("says nothing about a readable amount", () => {
    render(<LineFilterRow lines={[]} value={{ ...NO_LINE_FILTERS, min: "100", max: "1,234.50" }} onChange={vi.fn()} />);
    expect(screen.getByLabelText("Amount from").getAttribute("aria-invalid")).toBeNull();
    expect(screen.queryByText("An amount cannot be read, so it does not filter.")).toBeNull();
  });
});
