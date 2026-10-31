// 264 (plan E, F6; the owner's decision of 2026-10-31: the small lists the one list too): Settings › Users is the one list
// of the names, each opening its own page; "New user" is the title row's main action. Synthetic names, a mocked service.
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor } from "../../api";
import { setLanguage } from "../../i18n";
import hungarian from "../../i18n/hu-native.json";
import { linkCol, listPage } from "./listPage.testutil";
import { UsersPanel } from "./UsersPanel";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic owner"); sessionStorage.clear(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("Settings › Users", () => {
  it("lists the names, each opening its page, with New user in the title row", async () => {
    const query = vi.spyOn(api, "datasetQuery").mockResolvedValue(listPage("settings_users", [linkCol("name", "Name", "users")],
      [{ _key: "Synthetic owner", name: "Synthetic owner" }]));
    render(<UsersPanel />);
    expect(screen.getByRole("link", { name: "New user" }).getAttribute("href")).toBe("#/settings/users/new");
    const table = await screen.findByRole("table", { name: "Users" });
    expect(within(table).getByRole("link", { name: "Synthetic owner" }).getAttribute("href")).toBe("#/settings/users/Synthetic%20owner");
    expect(query.mock.calls[0][0]).toBe("settings_users");
  });

  it("has its words in Hungarian", () => {
    const hu = hungarian as Record<string, string>;
    for (const key of ["New user", "Added", "Remove from the list", "Remove {{name}} from the list?", "It is not on the list (any more)."]) {
      expect(hu[key], key).toBeTruthy();
      expect(hu[key]).not.toBe(key);
    }
  });
});
