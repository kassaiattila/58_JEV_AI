// 264 (plan E, F5; the owner's decision of 2026-10-31): the "Settings" crumb leads to Settings' own page - its groups,
// each section with what it is for - instead of the first section (Processes); the language is chosen with the theme
// on "Appearance and language" (the Language page only repeated the header's switch), its old address leads there.
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setActor } from "../../api";
import { setLanguage } from "../../i18n";
import hungarian from "../../i18n/hu-native.json";
import { parseRoute, routeHash } from "../../route";
import { Settings } from "../Settings";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); localStorage.clear(); sessionStorage.clear(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("Settings' own page", () => {
  it("is where the bare address and the Settings crumb lead", () => {
    expect(parseRoute("#/settings")).toEqual({ view: "settings", section: "" });
    expect(routeHash({ view: "settings", section: "" })).toBe("#/settings");
    expect(parseRoute("#/settings/language")).toEqual({ view: "settings", section: "appearance" });
  });

  it("lists every group with its sections and what each is for", () => {
    render(<Settings section="" />);
    expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeTruthy();
    const system = screen.getByRole("region", { name: "System" });
    expect(within(system).getByRole("link", { name: "Users" }).getAttribute("href")).toBe("#/settings/users");
    expect(within(system).getByText("The options of “Who is working?”")).toBeTruthy();
    expect(screen.getByRole("region", { name: "Shared library" })).toBeTruthy();
    expect(within(screen.getByRole("region", { name: "Processes" })).getByRole("link", { name: "All processes" })).toBeTruthy();
    const nav = screen.getByRole("navigation", { name: "Settings" });
    expect(within(nav).queryByRole("link", { name: "Language" })).toBeNull();
    expect(within(nav).getByRole("link", { name: "Appearance and language" })).toBeTruthy();
  });
});

describe("Appearance and language", () => {
  it("chooses the theme and the interface language on one page", () => {
    render(<Settings section="appearance" />);
    expect(screen.getByRole("heading", { level: 1, name: "Appearance and language" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: /As the system is set/ })).toBeTruthy();
    expect(screen.getByRole("group", { name: "Interface language" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "Magyar" })).toBeTruthy();
  });

  it("has its words in Hungarian", () => {
    const hu = hungarian as Record<string, string>;
    for (const key of ["Appearance and language", "As the system is set", "The theme and the interface language",
      "What each part of Settings is for"]) {
      expect(hu[key], key).toBeTruthy();
      expect(hu[key]).not.toBe(key);
    }
  });
});
