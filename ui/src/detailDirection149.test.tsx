// 149: the direction the own parties give an invoice contradicts its detailed type: the to-do says so in plain words.
import { describe, expect, it } from "vitest";
import { reasonText } from "./labels";

describe("the detailed type against the parties (149)", () => {
  it("names the type and the direction the parties give", () => {
    const text = reasonText("detect_detail:direction_mismatch:invoice_out:incoming");
    expect(text).toMatch(/^A részletes típus \(.+\) ellentmond a feleknek: szerintük a számla bejövő; ellenőrizd a típust$/);
  });
});
