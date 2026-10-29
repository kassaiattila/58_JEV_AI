// 160-D (plan F-csak-gpt Sz6, L6; decision 160 D3): which AI engine produced a result is shown with it. The engine is a
// fact about the run, not a state: a neutral mark with no state colour and no accent, on the release line beside the
// approval (172: the package's Approve and release, beside each open live run it approves), on the review bar and
// beside an email's recognised intent. An intent taken from another run, and a view from an older service, have no
// engine and show no mark. Artificial data, no service.
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type DsPage, type ItemResult, type PackageResult, type RunView, type WorkpackageView } from "./api";
import { EngineMark } from "./components/EngineMark";
import { setLanguage } from "./i18n";
import { EmailReview } from "./domains/email/EmailReview";
import { ResultStage } from "./views/ResultStage";

vi.mock("./components/DataTable", async () => {
  const React = await import("react");
  return { DataTable: ({ onPage }: { onPage?: (p: DsPage) => void }) => {
    React.useEffect(() => { onPage?.({ rows: [], review_version: "v1" } as unknown as DsPage); }, []); // eslint-disable-line react-hooks/exhaustive-deps
    return <div data-testid="table" />;
  } };
});

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("the AI engine mark", () => {
  it("names the engine and says what it did, with no state colour", () => {
    const { container } = render(<><EngineMark engine="gpt" /><EngineMark engine="jev" /><EngineMark engine={null} /></>);
    const marks = [...container.querySelectorAll(".engine-mark")] as HTMLElement[];
    expect(marks.map((m) => m.textContent)).toEqual(["AI engine: GPT only", "AI engine: JEV and GPT"]);
    expect(marks[0].title).toMatch(/GPT recognised .* JEV did not/);
    expect(marks[1].title).toMatch(/JEV recognised/);
    expect(marks.every((m) => !/\b(s-|status|primary|accent|warn|error)/.test(m.className))).toBe(true);
  });

  it("shows in Hungarian in the Hungarian interface", async () => {
    await setLanguage("hu");
    render(<EngineMark engine="gpt" />);
    expect(screen.getByText("AI-motor: Csak GPT")).toBeTruthy();
  });
});

const VIEW = { workpackage: { id: "wp-1", revision: 1 }, last_run: { run_id: "run-1" }, current_run: { run_id: "run-1", status: "done" },
  runs: 1 } as unknown as WorkpackageView;

function release(engine?: string | null, runId?: string) {
  vi.spyOn(api, "run").mockResolvedValue({ run: { run_id: "run-1", mode: "apply", status: "done", approval: null },
    tables: ["datapoints"], open_reasons: {}, review_version: "v1", ...(engine === undefined ? {} : { engine }) } as unknown as RunView);
  vi.spyOn(api, "datasetQuery").mockResolvedValue({ rows: [], review_version: "v1", result_mark: "m1" } as unknown as DsPage);
  vi.spyOn(api, "packageResult").mockResolvedValue({ workpackage_id: "wp-1", mark: "m1", open_live_runs: ["run-1"], removed_items: 0,
    blockers: [], state: "not_released", versions: [], tables: ["datapoints"],
    items: [{ item_id: "doc-1", kind: "document", file: "a.pdf", tier: "live", run_id: "run-1", final_status: "done", released: false }] } as PackageResult);
  return render(<ResultStage view={VIEW} runId={runId} onChanged={() => {}} />).container;
}

// 172: the package's Approve and release shows the engine of each open live run it approves; a run's own line shows its
describe("the release shows the engine of the run it approves", () => {
  it("a GPT only run carries its mark beside the release", async () => {
    const container = release("gpt");
    await waitFor(() => expect(container.querySelector(".release-line .engine-mark")).not.toBeNull());
    expect(container.querySelector(".release-line .engine-mark")?.textContent).toBe("AI engine: GPT only");
    expect(container.querySelector(".release-line button")?.className).toBe("primary"); // still the one main action
  });

  it("a run with JEV says so too, and a view from an older service shows no mark", async () => {
    const withJev = release("jev");
    await waitFor(() => expect(withJev.querySelector(".release-line .engine-mark")?.textContent).toBe("AI engine: JEV and GPT"));
    cleanup();
    const old = release();
    await waitFor(() => expect(old.querySelector(".release-line")).not.toBeNull());
    expect(old.querySelector(".engine-mark")).toBeNull();
  });

  it("a run's own line shows its engine", async () => {
    const container = release("gpt", "run-1");
    await waitFor(() => expect(container.querySelector(".release-line .engine-mark")?.textContent).toBe("AI engine: GPT only"));
  });
});

function mail(engine: string | null, fromThisRun = true): ItemResult {
  return {
    run_id: "run-000000000001", item_id: "a".repeat(64), kind: "email", extraction: null, source: null, provenance: {},
    open_reasons: [], earlier_open_reasons: [], engine,
    email: { subject: "Invoice", sender: null, sender_name: null, to: [], received_at: null, mailbox: null, body: "please find it attached",
      attachments: [], result: { intent: "szamlakuldes", intent_label: null, confidence: 0.97, next_flow: "m1:detect",
        attachments: [], from_this_run: fromThisRun, signals: {} }, tasks: null },
  } as unknown as ItemResult;
}

describe("an email's intent shows the engine that recognised it", () => {
  it("beside the model estimate of an intent from this run", () => {
    const { container } = render(<EmailReview data={mail("gpt")} onChanged={() => {}} />);
    expect(container.querySelector(".intent-box .engine-mark")?.textContent).toBe("AI engine: GPT only");
  });

  it("not for an intent taken from another run", () => {
    const { container } = render(<EmailReview data={mail(null, false)} onChanged={() => {}} />);
    expect(container.querySelector(".engine-mark")).toBeNull();
  });
});
