// 190 (plan 189 A2f; the owner's decision of 2026-10-21 "a setting, on by default"): the extraction of a quote request
// written in the email itself is a setting of the emails, with its own labels, and its follow-up's to-do reads as a
// sentence.
import { describe, expect, it } from "vitest";
import { PARAM_LABEL, paramApplies, paramShort, planLines, reasonText } from "./labels";

describe("the email text setting (190)", () => {
  it("has a label and short values", () => {
    expect(PARAM_LABEL.email_text).toBe("Aj\u00e1nlatk\u00e9r\u00e9s a lev\u00e9l sz\u00f6veg\u00e9b\u0151l");
    expect(paramShort("email_text", "extract")).toBe("kinyerve (GPT + JEV)");
    expect(paramShort("email_text", "off")).toBe("nincs kinyer\u00e9s");
  });
  it("acts on emails only", () => {
    expect(paramApplies("email_text", ["email"])).toBe(true);
    expect(paramApplies("email_text", ["document"])).toBe(false);
  });
  it("a follow-up that did not finish cleanly", () => {
    expect(reasonText("follow_up:needs_ocr")).toBe("A t\u00e9tel ut\u00f3lagos l\u00e9p\u00e9se nem z\u00e1rult le rendben (needs_ocr); n\u00e9zd meg k\u00e9zzel a t\u00e9telt");
  });
});

describe("the pre-start overview names the emails' text extraction (190)", () => {
  const plan = { documents: 0, emails: 2, attachments: 0, paths: { S: 0, G: 0, unknown: 0 }, tasks_emails: 0, text_emails: 2,
    azure: false, jev_reuse: true, arm: "auto", jev: true };
  it("with JEV", () => {
    expect(planLines(plan, { jev: "0.10", openai: "0.06" })).toContain(
      "OpenAI legfeljebb 0,06 USD: 2 levél: a szövegében írt ajánlatkérés kiolvasása.");
  });
});
