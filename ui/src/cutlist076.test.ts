// 076: a "none" answer on a cut candidate list is its own to-do, and it reads as a sentence with both counts.
import { describe, expect, it } from "vitest";
import { reasonText } from "./labels";

describe("076 cut candidate list", () => {
  it("names the field and how many of the candidates went to the model", () => {
    const text = reasonText("pick:none_on_cut_list:invoice_number:250/312");
    expect(text).toMatch(/le volt vágva/);
    expect(text).toMatch(/312 jelöltből 250 ment a modellnek/);
    expect(text).not.toMatch(/pick:|none_on_cut_list/);
  });
});
