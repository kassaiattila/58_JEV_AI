// 082 (the owner's decision of 2026-10-01): where a document type has no JEV path, GPT-based processing runs, so the
// S choice is "JEV where possible", not "JEV only". The pre-start overview says why documents go to GPT. Artificial
// data, no service.
import { describe, expect, it } from "vitest";
import type { RunPlan } from "./api";
import { paramShort, planLines } from "./labels";

const plan = (over: Partial<RunPlan>): RunPlan => ({ documents: 5, emails: 0, attachments: 0, paths: { S: 3, G: 2, unknown: 0 },
  tasks_emails: 0, azure: false, jev_reuse: true, ...over });

describe("082 the S path", () => {
  it("is named for what it does: JEV where possible, GPT elsewhere", () => {
    expect(paramShort("arm", "S")).toBe("JEV, ahol lehet — olcsóbb, tételsorok nélkül; máshol GPT (S)");
  });

  it("the overview says why documents go to GPT when S was chosen", () => {
    const lines = planLines(plan({ arm: "S" }), { jev: "0.25", openai: "0.30" });
    expect(lines).toContain("OpenAI legfeljebb 0,30 USD: 2 irat a G-úton, mert a típusának nincs JEV-útja.");
    expect(planLines(plan({ arm: "auto" }), { jev: "0.25", openai: "0.30" })).toContain("OpenAI legfeljebb 0,30 USD: 2 irat a G-úton.");
  });
});
