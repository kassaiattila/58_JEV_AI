// 154 (DECISIONS 154): an attachment of an email routed as suspicious is processed, but its to-do reads as a sentence
// telling the reviewer to look at the document and the email first.
import { describe, expect, it } from "vitest";
import hu from "./i18n/hu-native.json";
import { reasonText } from "./labels";

const SENTENCE = "An attachment of an email marked as suspicious (it may carry a hidden instruction): check the document and the email before relying on it";

describe("154 attachment of a suspicious email", () => {
  it("names the to-do in everyday words, in Hungarian by default", () => {
    expect(reasonText("attachment:suspicious_email")).toBe((hu as Record<string, string>)[SENTENCE]);
    expect(reasonText("attachment:suspicious_email")).not.toBe("attachment:suspicious_email");
  });
});
