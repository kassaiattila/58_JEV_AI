// 263 (plan E, E1; the owner's decisions of 2026-10-30): the shared parts of the one list and the one thing page - the
// table of contents (a branch opens and closes, the way to the chosen node stays open), the left panel (pinned, hidden
// to a strip, opened over the page, its width moved), a thing's previous and next in the order its list showed, and the
// list grouped by a column (a group's head with its count, closed and opened, the list's state kept for the way back).
// Invented data, a mocked service.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type DsPage } from "../api";
import { setLanguage } from "../i18n";
import { DataTable } from "./DataTable";
import { ItemSteps } from "./ItemSteps";
import { Navigator, type NavNode } from "./Navigator";
import { SidePanel } from "./SidePanel";

beforeEach(async () => { await setLanguage("en"); localStorage.clear(); sessionStorage.clear(); window.location.hash = ""; });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const TREE: NavNode[] = [
  { key: "g:a", label: "Library", children: [
    { key: "s:x", label: "Partners", href: "#/settings/x" },
    { key: "s:y", label: "Products", href: "#/settings/y", children: [{ key: "l:y/rules", label: "Rules", href: "#/settings/y/rules", count: 16 }] },
  ] },
  { key: "g:b", label: "System", children: [{ key: "s:z", label: "Users", href: "#/settings/z" }] },
];

describe("the table of contents (263)", () => {
  it("opens and closes a branch, keeps the way to the chosen node open, and finds a node by a search", () => {
    let open = new Set(["g:a", "g:b"]);
    const toggle = (k: string) => { open = new Set(open.has(k) ? [...open].filter((x) => x !== k) : [...open, k]); };
    const { rerender } = render(<Navigator nodes={TREE} selected="l:y/rules" open={open} onToggle={toggle} label="Settings" />);
    const nav = screen.getByRole("navigation", { name: "Settings" });
    // the chosen list's section is open though nobody opened it, with its count
    const rules = within(nav).getByRole("link", { name: /Rules/ });
    expect(rules.getAttribute("aria-current")).toBe("page");
    expect(within(rules).getByText("16")).toBeTruthy();
    fireEvent.click(within(nav).getByRole("button", { name: "System" }));
    rerender(<Navigator nodes={TREE} selected="l:y/rules" open={open} onToggle={toggle} label="Settings" />);
    expect(within(nav).queryByRole("link", { name: "Users" })).toBeNull();
    expect(within(nav).getByRole("button", { name: "System" }).getAttribute("aria-expanded")).toBe("false");
    // a search shows the matching nodes with the way to them, the closed branch's too
    rerender(<Navigator nodes={TREE} selected={null} open={open} onToggle={toggle} query="user" onQuery={() => undefined} label="Settings" />);
    expect(within(nav).getAllByRole("link").map((a) => a.textContent)).toEqual(["Users"]);
  });
});

describe("the left panel (263)", () => {
  it("is pinned at first, hides to a strip, opens over the page and pins again", () => {
    render(<SidePanel id="test" label="Contents"><p>the tree</p></SidePanel>);
    expect(screen.getByText("the tree")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Hide" }));
    expect(screen.queryByText("the tree")).toBeNull();
    expect(JSON.parse(localStorage.getItem("jav.panel.test")!)).toEqual({ pinned: false, width: 264 });
    const reveal = screen.getByRole("button", { name: "Contents" });
    fireEvent.click(reveal);
    expect(reveal.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("complementary", { name: "Contents" }).className).toContain("floating");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByText("the tree")).toBeNull();
    fireEvent.click(reveal);
    fireEvent.click(screen.getByRole("button", { name: "Pin" }));
    expect(screen.getByRole("complementary", { name: "Contents" }).className).not.toContain("floating");
  });

  it("closes over the page when a node is chosen", async () => {
    localStorage.setItem("jav.panel.test", JSON.stringify({ pinned: false, width: 300 }));
    render(<SidePanel id="test" label="Contents"><a href="#/settings/z">Users</a></SidePanel>);
    fireEvent.click(screen.getByRole("button", { name: "Contents" }));
    expect(screen.getByRole("link", { name: "Users" })).toBeTruthy();
    await act(async () => { window.location.hash = "#/settings/z"; window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(screen.queryByRole("link", { name: "Users" })).toBeNull();
  });

  it("moves its width with the keyboard on its edge, within its bounds, and keeps it", () => {
    render(<SidePanel id="test" label="Contents"><p>the tree</p></SidePanel>);
    const edge = screen.getByRole("separator", { name: "Width of the panel" });
    fireEvent.keyDown(edge, { key: "ArrowRight" });
    expect(edge.getAttribute("aria-valuenow")).toBe("280");
    for (let i = 0; i < 20; i++) fireEvent.keyDown(edge, { key: "ArrowLeft" });
    expect(edge.getAttribute("aria-valuenow")).toBe("200");
    expect(JSON.parse(localStorage.getItem("jav.panel.test")!).width).toBe(200);
  });
});

describe("a thing's previous and next (263)", () => {
  it("steps in the order its list showed, and shows nothing for a thing opened from elsewhere", () => {
    sessionStorage.setItem("jav.table.things.order", JSON.stringify(["#/settings/x/1", "#/settings/x/2", "#/settings/x/3"]));
    window.location.hash = "#/settings/x/2?open=a";
    const { unmount } = render(<ItemSteps list="things" />);
    expect(screen.getByRole("link", { name: "← Previous" }).getAttribute("href")).toBe("#/settings/x/1");
    expect(screen.getByRole("link", { name: "Next →" }).getAttribute("href")).toBe("#/settings/x/3");
    unmount();
    window.location.hash = "#/settings/x/3";
    const { unmount: gone } = render(<ItemSteps list="things" />);
    expect(screen.queryByRole("link", { name: "Next →" })).toBeNull();  // the last: no next
    gone();
    window.location.hash = "#/settings/x/9";
    const { container } = render(<ItemSteps list="things" />);
    expect(container.textContent).toBe("");
  });
});

const COLS: DsPage["columns"] = [
  { key: "title", label: "Title", kind: "text", hidden: false, labels: null, link: "settings", section: "products", list: "rules" },
  { key: "kind", label: "Kind", kind: "enum", hidden: false, labels: { a: "Alpha", b: "Beta" }, group: true },
  { key: "state", label: "State", kind: "enum", hidden: false, labels: { active: "Active" }, badge: true, marks: { active: "done" } },
];
const ROWS = [
  { _key: "r1", title: "One", kind: "a", state: "active" }, { _key: "r2", title: "Two", kind: "a", state: "active" },
  { _key: "r3", title: "Three", kind: "b", state: "active" },
];
const page = (group?: string): DsPage => ({ dataset: { name: "things", label: "Things", scope: [], optional_scope: [] }, columns: COLS,
  rows: ROWS, total: 3, matched: 3, offset: 0, limit: 100, facets: {},
  ...(group ? { group, groups: [{ value: "a", count: 2 }, { value: "b", count: 1 }] } : {}) });

describe("the one list, grouped (263)", () => {
  it("asks for a group, heads each group with its count, closes one, and keeps its state for the way back", async () => {
    const query = vi.spyOn(api, "datasetQuery").mockImplementation(async (_n, _s, q) => page(q.group));
    const { unmount } = render(<DataTable dataset="things" label="Things" persist="things" />);
    await screen.findByRole("link", { name: "One" });
    expect(screen.getByRole("link", { name: "Three" }).getAttribute("href")).toBe("#/settings/products/rules/r3");
    expect(screen.getAllByText("Active")[0].className).toBe("status s-done");  // a badge's mark by its value
    // the order of the rows' pages, for a thing's previous and next
    expect(JSON.parse(sessionStorage.getItem("jav.table.things.order")!)).toEqual(
      ["#/settings/products/rules/r1", "#/settings/products/rules/r2", "#/settings/products/rules/r3"]);
    fireEvent.click(screen.getByRole("button", { name: "Group by" }));
    fireEvent.click(screen.getByRole("option", { name: "Grouped by Kind" }));
    await waitFor(() => expect(query).toHaveBeenLastCalledWith("things", {}, expect.objectContaining({ group: "kind" })));
    const alpha = await screen.findByRole("button", { name: /Alpha/ });
    expect(alpha.textContent).toBe("Alpha2");
    fireEvent.click(alpha);  // closed: its rows are not drawn, its head stays
    expect(screen.queryByRole("link", { name: "One" })).toBeNull();
    expect(screen.getByRole("link", { name: "Three" })).toBeTruthy();
    expect(alpha.getAttribute("aria-expanded")).toBe("false");
    unmount();
    render(<DataTable dataset="things" label="Things" persist="things" />);  // back to the list: as it was
    await screen.findByRole("link", { name: "Three" });
    expect(screen.queryByRole("link", { name: "One" })).toBeNull();
    expect(query).toHaveBeenLastCalledWith("things", {}, expect.objectContaining({ group: "kind" }));
  });
});
