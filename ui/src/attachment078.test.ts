// 078: an unreadable PDF attachment gives the email a to-do with an everyday sentence (the email itself still runs).
import { describe, expect, it } from "vitest";
import { reasonText } from "./labels";

describe("078 unreadable attachment", () => {
  it("names the to-do in everyday words", () => {
    expect(reasonText("attachment:unreadable:PdfReaderError")).toMatch(/PDF-csatolmány nem olvasható/);
    expect(reasonText("attachment:unreadable:timeout")).toMatch(/szándéka ettől még elkészült/);
  });
});
