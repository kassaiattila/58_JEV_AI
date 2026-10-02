// 091 (GPT field confidence, the owner's decision of 2026-10-02): on the path without JEV a field's confidence is the
// token probability of the GPT answer, capped by the source check; the tooltip says which one it is. A field without a
// basis keeps the earlier text. Artificial data; the interface runs in English so the test holds no Hungarian text.
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import type { Provenance } from "./api";
import { setLanguage } from "./i18n";
import { confidenceTitle } from "./review/FieldPanel";

beforeAll(async () => { await setLanguage("en"); });
afterAll(async () => { await setLanguage("hu"); });

const prov = (over: Partial<Provenance>): Provenance => ({ status: "located", method: "search", alternatives: [], ...over });
const gpt = (token: number | null) => ({ source: "gpt" as const, measure: "joint", token, failed_check: false });

describe("091 GPT confidence tooltip", () => {
  it("no confidence: no estimate", () => {
    expect(confidenceTitle(prov({ confidence: null }))).toBe("No estimate");
    expect(confidenceTitle(undefined)).toBe("No estimate");
  });

  it("a JEV or candidate confidence keeps the model text", () => {
    expect(confidenceTitle(prov({ confidence: 0.93 }))).toBe("Model confidence: 93%");
  });

  it("a GPT confidence names its basis", () => {
    expect(confidenceTitle(prov({ confidence: 0.97, confidence_basis: gpt(0.97) }))).toMatch(/GPT estimate: 97%.*probability of the answer/);
    expect(confidenceTitle(prov({ confidence: 0.5, status: "not_found", confidence_basis: gpt(0.97) })))
      .toMatch(/GPT estimate: 50%.*97%.*lowered/);
    expect(confidenceTitle(prov({ confidence: 0.5, status: "not_found", confidence_basis: gpt(null) })))
      .toMatch(/GPT estimate: 50%.*source check only/);
  });
});
