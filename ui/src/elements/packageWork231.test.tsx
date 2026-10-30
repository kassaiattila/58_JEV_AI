// 231 (plan stage C, C3b3; DECISIONS 231): the documents' and the bank statements' process packs - the wizard's general
// form asks for the case's documents (a folder, with its subfolders or not, or chosen files), and the case page's
// document processing element shows the package the case made, starts its live run with the cost cap on the button and
// leads to the package's own pages. Synthetic data, a mocked service.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type CaseView, type PackageWorkView } from "../api";
import hungarian from "../i18n/hu-native.json";
import { setLanguage } from "../i18n";
import { PackageWork } from "./PackageWork";
import { packageWorkLine } from "./packageWorkStatus";
import { ProcessCreate } from "./ProcessStart";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const CASE = "wp-000000000b33";
const WP = "wp-000000000b34";
const PARTY = "party-0000000000a1";
const PACKS = { processes: [
  { id: "documents", title: "Documents", version: "1.0.0", scope: ["source"], asks: ["source"], package_kinds: [] },
  { id: "bank_statements", title: "Bank statements", version: "1.0.0", scope: ["party", "period", "source"],
    asks: ["party", "period", "source"], package_kinds: [] },
] };

function mockStart() {
  vi.spyOn(api, "processes").mockResolvedValue(PACKS);
  vi.spyOn(api, "workpackagesBrief").mockResolvedValue({ workpackages: [] } as never);
  vi.spyOn(api, "ownParties").mockResolvedValue({ parties: [{ id: PARTY, name: "Example Home" }] } as never);
  return vi.spyOn(api, "startCase").mockResolvedValue({ case_id: CASE });
}

describe("the wizard's form asks for the case's documents (231 C3b3)", () => {
  it("sends a folder with its subfolders and names the case after the folder", async () => {
    const start = mockStart();
    const done = vi.fn();
    render(<ProcessCreate pack="documents" onDone={done} />);
    const create = await screen.findByRole("button", { name: "Create" }) as HTMLButtonElement;
    expect(create.disabled).toBe(true); // no folder yet
    fireEvent.change(screen.getByLabelText("The folder's full path"), { target: { value: "C:\\invoices\\2026-04" } });
    fireEvent.click(screen.getByLabelText("Its subfolders too"));
    fireEvent.click(create);
    await waitFor(() => expect(done).toHaveBeenCalledWith(CASE));
    expect(start).toHaveBeenCalledWith({ pack: "documents", name: "Documents · 2026-04",
      source: { kind: "folder", folder: "C:\\invoices\\2026-04", recursive: true } });
  });

  it("sends the chosen files, one a line, with the party and the period of a statements case", async () => {
    const start = mockStart();
    render(<ProcessCreate pack="bank_statements" onDone={vi.fn()} />);
    fireEvent.change(await screen.findByLabelText("Own party"), { target: { value: PARTY } });
    fireEvent.change(screen.getByLabelText("Period from"), { target: { value: "2026-04-01" } });
    fireEvent.change(screen.getByLabelText("to"), { target: { value: "2026-04-30" } });
    fireEvent.click(screen.getByRole("radio", { name: "Chosen files" }));
    fireEvent.change(screen.getByLabelText("The files' full paths, one a line"),
      { target: { value: "C:\\bank\\april.xml\n\n  C:\\bank\\april.pdf  " } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(start).toHaveBeenCalled());
    expect(start).toHaveBeenCalledWith({ pack: "bank_statements", name: "Bank statements · Example Home · 2026-04-01 – 2026-04-30",
      party_id: PARTY, period_start: "2026-04-01", period_end: "2026-04-30",
      source: { kind: "files", files: ["C:\\bank\\april.xml", "C:\\bank\\april.pdf"] } });
  });
});

const VIEW: PackageWorkView = { package: { id: WP, name: "April invoices", items: 3, kind: "folder" }, runs: [], can_start: true,
  estimate: { jev: "0.12", openai: "0.03" }, blockers: [] };
const page = (state: string) => ({
  case: { id: CASE, pack: "documents", version: "1.0.0", title: "Documents", name: "April invoices", status: "open" },
  steps: { process: { title: "Processing", uses: "process_documents@1", start: "auto", state, phase: null, waiting_for: "run_start",
    awaiting_start: false, note: null, result: null,
    // 261 (B1e): the service names the start with its cost cap, the shared actions show it
    actions: [{ name: "start_run", label: "Start the live run", cap: { jev: "0.12", openai: "0.03" } }] } },
  next: null, tabs: [],
} as unknown as CaseView);
const props = (data: PackageWorkView | null, state = "running") => ({
  caseId: CASE, element: { type: "package_work", step: "process", data }, page: page(state), onChanged: vi.fn(),
});

describe("the case page's document processing element (231 C3b3)", () => {
  it("starts the package's live run with its cost cap on the button and leads to the package's pages", async () => {
    const act = vi.spyOn(api, "caseStepAction").mockResolvedValue(page("running"));
    const p = props(VIEW);
    render(<PackageWork {...p} />);
    expect(screen.getByRole("heading", { name: "The case's documents" }).getAttribute("title")).toBe("April invoices");
    expect(screen.getByText("3 documents")).toBeTruthy();
    const button = screen.getByRole("button", { name: /Start the live run/ });
    expect(button.textContent).toContain("≤ 0.15 USD");
    expect(button.getAttribute("title")).toBe("Start the live run: it can spend up to 0.15 USD");
    fireEvent.click(button);
    await waitFor(() => expect(act).toHaveBeenCalledWith(CASE, "process", "start_run"));
    await waitFor(() => expect(p.onChanged).toHaveBeenCalled());
    const pages = screen.getByRole("navigation", { name: "The batch's pages" });
    expect([...pages.querySelectorAll("a")].map((a) => a.getAttribute("href"))).toEqual(
      // 261 (B1c): under the case's address
      [`#/cases/${CASE}/batches/${WP}/process`, `#/cases/${CASE}/batches/${WP}/review`, `#/cases/${CASE}/batches/${WP}/result`]);
  });

  it("lists the live runs once one has started, and offers no second start", () => {
    const running = { ...VIEW, can_start: false, runs: [{ run_id: "run-1", mode: "apply", status: "running", approval: null }] };
    render(<PackageWork {...props(running)} />);
    expect(screen.queryByRole("button", { name: /Start the live run/ })).toBeNull();
    expect(screen.getByRole("link", { name: "run-1" }).getAttribute("href")).toBe("#/runs/run-1");
  });

  it("names a finished run's state, not its code (U1)", () => {
    const done = { ...VIEW, can_start: false, runs: [{ run_id: "run-2", mode: "apply", status: "done", approval: null }] };
    render(<PackageWork {...props(done)} />);
    expect(screen.getByText("Done")).toBeTruthy();
    expect(screen.queryByText("done")).toBeNull();
  });

  it("says why a case has no package", () => {
    const { unmount } = render(<PackageWork {...props({ package: null }, "done")} />);
    expect(screen.getByText("The source held no document: the case is done without a batch.")).toBeTruthy();
    unmount();
    render(<PackageWork {...props({ package: null })} />);
    expect(screen.getByText("The batch is being made…")).toBeTruthy();
  });

  it("gives its tab a line of the documents and where the live run stands", () => {
    expect(packageWorkLine(null)).toBeNull();
    expect(packageWorkLine({ package: null })).toBe("no documents");
    expect(packageWorkLine(VIEW)).toBe("3 documents · waiting for its live run");
    expect(packageWorkLine({ ...VIEW, runs: [{ run_id: "r", mode: "trial", status: "done", approval: null }] }))
      .toBe("3 documents · waiting for its live run");  // a trial is not the live run
    expect(packageWorkLine({ ...VIEW, runs: [{ run_id: "r", mode: "apply", status: "running", approval: null }] }))
      .toBe("3 documents · live run in progress");
    expect(packageWorkLine({ ...VIEW, runs: [{ run_id: "r", mode: "apply", status: "done", approval: "a1" }] }))
      .toBe("3 documents · approved");
    // U1 (the walkthrough): a live run that has ended waits for its approval or its to-dos, not "in progress"
    expect(packageWorkLine({ ...VIEW, runs: [{ run_id: "r", mode: "apply", status: "done", approval: null }] }))
      .toBe("3 documents · its live run waits for approval");
    expect(packageWorkLine({ ...VIEW, runs: [{ run_id: "r", mode: "apply", status: "needs_review", approval: null }] }))
      .toBe("3 documents · its live run has to-dos");
    expect(packageWorkLine({ ...VIEW, runs: [{ run_id: "r", mode: "apply", status: "failed", approval: null }] }))
      .toBe("3 documents · its live run stopped");
  });

  it("has a Hungarian translation for every new label", () => {
    const labels = ["The case's documents", "Chosen files", "The folder's full path", "Its subfolders too",
      "The files' full paths, one a line", "Start the live run", "Starts the package's live run, which can spend up to {{usd}}",
      "The package is being made…", "The package's pages", "The source held no document: the case is done without a package.",
      "live run in progress", "no documents", "waiting for its live run", "Processing", "Review", "Result",
      "its live run waits for approval", "its live run has to-dos", "its live run stopped"];
    expect(labels.filter((l) => !(l in hungarian))).toEqual([]);
  });
});

describe("the mailbox download as a case (231 C3d)", () => {
  it("the general form asks for the download and starts the case with it", async () => {
    vi.spyOn(api, "processes").mockResolvedValue({ processes: [{ id: "mailbox", title: "Emails from a mailbox", version: "1.0.0",
      scope: ["source"], asks: ["source"], package_kinds: [], source_kinds: ["mailbox"] }] });
    vi.spyOn(api, "workpackagesBrief").mockResolvedValue({ workpackages: [] } as never);
    vi.spyOn(api, "ownParties").mockResolvedValue({ parties: [] } as never);
    vi.spyOn(api, "mailbox").mockResolvedValue({ accounts: ["office@example.com"], schedules: [], pulls: [], bridge_available: true } as never);
    const start = vi.spyOn(api, "startCase").mockResolvedValue({ case_id: CASE });
    const done = vi.fn();
    render(<ProcessCreate pack="mailbox" onDone={done} />);
    const create = await screen.findByRole("button", { name: "Create" }) as HTMLButtonElement;
    expect(create.disabled).toBe(true);  // no address yet
    fireEvent.click(await screen.findByRole("button", { name: "office@example.com" }));  // a previously used one
    await waitFor(() => expect(create.disabled).toBe(false));
    fireEvent.click(create);
    await waitFor(() => expect(done).toHaveBeenCalledWith(CASE));
    const body = start.mock.calls[0][0];
    expect(body.source).toEqual({ kind: "mailbox", request: { accounts: ["office@example.com"], folders: ["Inbox"], subfolders: false,
      max_items: 0, since_days: 7 } });
    // 231 (U3, the backlog's mailbox case name): without a name of its own, the case is named by its mailbox and period
    expect(body.name).toBe("Emails from a mailbox · office@example.com · the last 7 days");
  });

  it("the case page offers the processes that read its package (the owner's decision of 2026-10-26)", () => {
    const offered = { ...VIEW, package: { ...VIEW.package!, kind: "mailbox" },
      offers: [{ pack: "mail_routing", title: "Email routing", name: "Email routing: Mail", sources: [WP], cases: [] }] };
    render(<PackageWork {...props(offered)} />);
    expect(screen.getByRole("button", { name: /Start a case/ })).toBeTruthy();
  });
});
