// 091 (GPT field confidence, the owner's decisions of 2026-10-02: "probability only, 0.98" and "display only, trial
// first"): on the path without JEV a field's confidence is the token probability of the GPT answer, lowered only by a
// failed field check; it has its own band (confident from 0.98), so the review's colours and its "uncertain" filter
// treat a GPT field at 95% as "to check" while a JEV field at 95% stays confident. The tooltip says which estimate it
// is. Artificial data; the interface runs in English so the test holds no Hungarian text.
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import type { ItemResult, Provenance } from "./api";
import { setLanguage } from "./i18n";
import { confidenceTitle } from "./review/FieldPanel";
import { classifyFields } from "./review/fieldFilter";
import { bandOf, bandsFor, type Bands } from "./review/geometry";

beforeAll(async () => { await setLanguage("en"); });
afterAll(async () => { await setLanguage("hu"); });

const prov = (over: Partial<Provenance>): Provenance => ({ status: "located", method: "search", alternatives: [], ...over });
const gpt = (token: number | null, failed = false) => ({ source: "gpt" as const, measure: "joint", token, failed_check: failed });
const BANDS: Bands = { confident: 0.9, check: 0.5, gpt: { confident: 0.98, check: 0.5 } };

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
    expect(confidenceTitle(prov({ confidence: 0.5, confidence_basis: gpt(0.97, true) })))
      .toMatch(/GPT estimate: 50%.*97%.*field check failed/);
    expect(confidenceTitle(prov({ confidence: 0.5, confidence_basis: gpt(null, true) })))
      .toMatch(/GPT estimate: 50%.*field check only/);
  });
});

describe("091 GPT band", () => {
  it("a GPT field has its own band; other fields keep theirs", () => {
    const g = prov({ confidence: 0.95, confidence_basis: gpt(0.95) });
    const j = prov({ confidence: 0.95 });
    expect(bandOf(g.confidence, bandsFor(g, BANDS))).toBe("check");
    expect(bandOf(j.confidence, bandsFor(j, BANDS))).toBe("confident");
    expect(bandOf(0.99, bandsFor(prov({ confidence_basis: gpt(0.99) }), BANDS))).toBe("confident");
    expect(bandsFor(g, { confident: 0.9, check: 0.5 })).toEqual({ confident: 0.9, check: 0.5 }); // an older service
  });

  it("the uncertain filter uses it", () => {
    const res = {
      open_reasons: [], correction: { confirmed: {} },
      provenance: { a: prov({ confidence: 0.95, confidence_basis: gpt(0.95) }), b: prov({ confidence: 0.95 }) },
    } as unknown as ItemResult;
    expect(classifyFields(["a", "b"], res, BANDS).uncertain).toEqual(["a"]);
  });
});
