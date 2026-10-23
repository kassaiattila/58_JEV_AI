// 216 (plan G-process-core P2e): "Waiting for me" — the header shows the person's count beside "My work today", and the
// page lists their open tasks and anyone's with where each is done; the switch adds trial runs and measurements.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { api, setActor, type DsColumn, type DsPage, type DsRow } from "./api";
import { setLanguage } from "./i18n";
import { parseRoute, routeHash } from "./route";
import { Waiting } from "./views/Waiting";

const COLUMNS: DsColumn[] = [
  { key: "kind", label: "Kind", kind: "enum", hidden: false, labels: { review: "To-do", run_approval: "Run approval" } },
  { key: "what", label: "What", kind: "text", hidden: false, labels: null, link: "next" },
  { key: "workpackage_name", label: "Work package", kind: "text", hidden: false, labels: null, link: "workpackage" },
  { key: "origin", label: "Origin", kind: "enum", hidden: false, labels: { live: "Live", trial: "Trial" } },
  { key: "assignee", label: "For", kind: "enum", hidden: false, labels: { mine: "You", anyone: "Anyone" } },
  { key: "reason", label: "First to-do", kind: "text", hidden: false, labels: null },
];
const ROWS: DsRow[] = [
  { _key: "review:7", kind: "review", what: "szamla_12.pdf", workpackage_name: "Szeptember", origin: "live", assignee: "mine",
    reason: "pick:supplier", _wp: "wp-1", _stage: "review/abc" },
  { _key: "run_approval:r1", kind: "run_approval", what: "Live run", workpackage_name: "Szeptember", origin: "live",
    assignee: "anyone", reason: null, _wp: "wp-1", _stage: "result" },
];

function page(name: string, rows: DsRow[], total = rows.length): DsPage {
  return { dataset: { name, label: name, scope: ["actor"], optional_scope: ["all"] }, columns: COLUMNS, rows, total,
    matched: rows.length, offset: 0, limit: 50, facets: {} };
}

beforeEach(async () => { await setLanguage("en"); });
afterEach(async () => {
  vi.restoreAllMocks();
  setActor("");
  window.location.hash = "";
  await setLanguage("hu");
});

describe("Waiting for me (216)", () => {
  it("has its own address, with or without trial runs and measurements", () => {
    expect(parseRoute("#/waiting")).toEqual({ view: "waiting" });
    expect(parseRoute("#/waiting?all=1")).toEqual({ view: "waiting", all: true });
    expect(routeHash({ view: "waiting" })).toBe("#/waiting");
    expect(routeHash({ view: "waiting", all: true })).toBe("#/waiting?all=1");
  });

  it("shows the person's count in the header before My work today", async () => {
    setActor("Teszt Elek");
    vi.spyOn(api, "users").mockResolvedValue({ users: ["Teszt Elek"] });
    vi.spyOn(api, "worker").mockResolvedValue({ running: true, stop_requested: false, jobs: {} });
    const query = vi.spyOn(api, "datasetQuery").mockImplementation(async (name) => page(name, name === "waiting" ? ROWS : [], name === "waiting" ? 3 : 0));
    render(<App />);
    const link = await screen.findByRole("link", { name: /Waiting for me/ });
    expect(link.getAttribute("href")).toBe("#/waiting");
    await waitFor(() => expect(link.querySelector(".count-alert")?.textContent).toBe("3"));
    expect(query).toHaveBeenCalledWith("waiting", { actor: "Teszt Elek" }, { limit: 1 });
    const today = screen.getByRole("link", { name: "My work today" });
    expect(link.compareDocumentPosition(today) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("lists the tasks with where each is done, and the switch adds trial runs and measurements", async () => {
    setActor("Teszt Elek");
    const query = vi.spyOn(api, "datasetQuery").mockResolvedValue(page("waiting", ROWS));
    const user = userEvent.setup();
    render(<Waiting all={false} />);
    expect(await screen.findByRole("link", { name: "szamla_12.pdf" })).toHaveProperty("hash", "#/workpackages/wp-1/review/abc");
    expect(screen.getByRole("link", { name: "Live run" })).toHaveProperty("hash", "#/workpackages/wp-1/result");
    expect(screen.getByText("Anyone")).toBeTruthy();
    expect(query.mock.calls[0].slice(0, 2)).toEqual(["waiting", { actor: "Teszt Elek" }]);
    await user.click(screen.getByRole("checkbox", { name: "Trial runs and measurements too" }));
    expect(window.location.hash).toBe("#/waiting?all=1");
  });

  it("asks for a name first", () => {
    render(<Waiting all={false} />);
    expect(screen.getByText(/Choose your name in the/)).toBeTruthy();
  });
});
