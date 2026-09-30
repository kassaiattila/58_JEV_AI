// 061 decision: active user + assignment. In the header a name must be chosen from the name list (a stored name that is
// not on the list does not count as chosen); the Users list is saved at once; the „Mai munkám” (My work today) title;
// „Csak a saját csomagjaim” (Only my own packages).
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { api, getActor, setActor, type DsPage } from "./api";
import { parseRoute, routeHash } from "./route";
import { UsersPanel } from "./views/settings/UsersPanel";

const EMPTY: DsPage = {
  dataset: { name: "workpackages", label: "Munkacsomagok", scope: [], optional_scope: ["include_archived", "owner"] }, columns: [], rows: [],
  total: 0, matched: 0, offset: 0, limit: 50, facets: {},
};

afterEach(() => {
  vi.restoreAllMocks();
  setActor("");
  window.location.hash = "";
});

function shell(users: string[]) {
  vi.spyOn(api, "users").mockResolvedValue({ users });
  vi.spyOn(api, "worker").mockResolvedValue({ running: true, stop_requested: false, jobs: {} });
  return vi.spyOn(api, "datasetQuery").mockResolvedValue(EMPTY);
}

describe("Ki dolgozik? (061)", () => {
  it("nem üres listánál a listán nem szereplő tárolt név nem kiválasztott; választás után „Mai munkám”", async () => {
    setActor("Régi Név");
    shell(["Minta Anna", "Teszt Elek"]);
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByText("Módosítás előtt válaszd ki a neved.")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Ki dolgozik?" }));
    await user.click(await screen.findByRole("option", { name: "Minta Anna" }));
    expect(getActor()).toBe("Minta Anna");
    expect(await screen.findByRole("link", { name: "Mai munkám" })).toBeTruthy();
    expect(screen.queryByText("Módosítás előtt válaszd ki a neved.")).toBeNull();
  });

  it("üres listánál szabadon írható, és a Felhasználók felvételére hivatkozik", async () => {
    shell([]);
    render(<App />);
    expect(await screen.findByRole("link", { name: "Felhasználók felvétele" })).toBeTruthy();
    expect(screen.getByLabelText("Ki dolgozik?")).toBeTruthy();
  });

  it("„Csak a saját csomagjaim”: a lista a felelős szerint szűr", async () => {
    setActor("Minta Anna");
    const query = shell(["Minta Anna"]);
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("checkbox", { name: "Csak a saját csomagjaim" }));
    await waitFor(() => expect(query).toHaveBeenLastCalledWith("workpackages", { owner: "Minta Anna" }, expect.anything()));
  });
});

describe("Felhasználók listája (061)", () => {
  it("a felvétel és a törlés azonnal mentődik, külön Mentés nélkül", async () => {
    vi.spyOn(api, "users").mockResolvedValue({ users: ["Minta Anna"] });
    const save = vi.spyOn(api, "saveUsers").mockImplementation(async (users) => ({ users }));
    const user = userEvent.setup();
    render(<UsersPanel />);
    await screen.findByText("Minta Anna");
    await user.type(screen.getByLabelText("Új név"), "Teszt Elek");
    await user.click(screen.getByRole("button", { name: "Felvétel" }));
    expect(save).toHaveBeenLastCalledWith(["Minta Anna", "Teszt Elek"]);
    expect(await screen.findByText("Teszt Elek felvéve és mentve.")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Minta Anna törlése a listából" }));
    await user.click(screen.getByRole("button", { name: "Biztosan? Kattints újra" })); // 073: two-click confirmation
    expect(save).toHaveBeenLastCalledWith(["Teszt Elek"]);
    expect(screen.queryByRole("button", { name: "Mentés" })).toBeNull();
    expect(within(screen.getByRole("region", { name: "Felhasználók" })).queryByText("Mentetlen módosítás van.")).toBeNull();
  });
});

describe("Felhasználónév szabálya (066 Á25)", () => {
  it("a szerző-fejlécben nem használható nevet mentés előtt magyarul elutasítja", async () => {
    vi.spyOn(api, "users").mockResolvedValue({ users: ["Minta Anna"] });
    const save = vi.spyOn(api, "saveUsers").mockImplementation(async (users) => ({ users }));
    const user = userEvent.setup();
    render(<UsersPanel />);
    await screen.findByText("Minta Anna");
    await user.type(screen.getByLabelText("Új név"), "O'Brien");
    await user.click(screen.getByRole("button", { name: "Felvétel" }));
    expect(save).not.toHaveBeenCalled();
    expect((await screen.findByRole("alert")).textContent).toContain("A név csak betűt, számot, szóközt, pontot, @ jelet és kötőjelet tartalmazhat");
    await user.clear(screen.getByLabelText("Új név"));
    await user.type(screen.getByLabelText("Új név"), "Kővári Ödön");
    await user.click(screen.getByRole("button", { name: "Felvétel" }));
    expect(save).toHaveBeenLastCalledWith(["Minta Anna", "Kővári Ödön"]);
  });
});

describe("Mai munkám címe (061)", () => {
  it("nap nélkül és nappal is visszaalakítható", () => {
    expect(parseRoute("#/activity")).toEqual({ view: "activity", day: undefined });
    expect(parseRoute("#/activity?day=2026-09-27")).toEqual({ view: "activity", day: "2026-09-27" });
    expect(parseRoute("#/activity?day=tegnap")).toEqual({ view: "activity", day: undefined });
    expect(routeHash({ view: "activity", day: "2026-09-27" })).toBe("#/activity?day=2026-09-27");
  });
});
