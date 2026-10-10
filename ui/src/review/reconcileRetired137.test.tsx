// 137 (DECISIONS 137): the review page no longer shows proposed invoice <-> statement line pairs; the reconciliation
// package does that work. The pair to-dos opened from 129 to 136 keep their names in a run's history. Expectations
// avoid Hungarian letters for the language guard.
import { beforeEach, describe, expect, it } from "vitest";
import { RESULT_TABLES } from "../route";
import { setLanguage } from "../i18n";
import { reasonText } from "../labels";

const INVOICE = "a".repeat(64);
const LINE = `${"b".repeat(16)}:0a1b2c3d4e5f:0`;

beforeEach(async () => { await setLanguage("hu"); });

describe("the retired pair panel (137)", () => {
  it("keeps the names of the earlier pair to-dos", () => {
    expect(reasonText(`reconcile:proposed:${INVOICE.slice(0, 16)}:${LINE}`)).toMatch(/Lehets.ges kifizet.s/);
    expect(reasonText(`reconcile:amount_only:${INVOICE.slice(0, 16)}:${LINE}`)).toMatch(/^Eld.ntend. lehets.ges kifizet.s/);
  });

  it("has no reconciliation view among a run's results", () => {
    expect(RESULT_TABLES as string[]).not.toContain("reconciliation");
  });
});
