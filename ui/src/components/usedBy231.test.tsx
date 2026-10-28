// 231 (stage U, U3d; the owner's decisions of 2026-10-28: every shared element says which processes use it): a shared
// element names the processes that use it, each a link to its settings page, or says that none does; the list of a
// kind is asked once, however many rows show it; the partner register names the processes of the chosen role.
// Invented data, a mocked service.
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type PartnerRoles } from "../api";
import { setLanguage } from "../i18n";
import hungarian from "../i18n/hu-native.json";
import { routeHash } from "../route";
import { PartnersPanel } from "../views/settings/PartnersPanel";
import { UsedBy, useUsedBy } from "./UsedBy";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const USED = { invented_product: [{ id: "invented_offer", title: "Invented offer" }, { id: "invented_renewal", title: "Invented renewal" }] };

function Rows({ idents }: { idents: string[] }) {
  const used = useUsedBy("product");
  return <ul>{idents.map((i) => <li key={i} aria-label={i}><UsedBy used={used} ident={i} /></li>)}</ul>;
}

describe("what uses a shared element (231 U3d)", () => {
  it("names the processes as links to their pages, or says none does, asking once for the kind", async () => {
    const asked = vi.spyOn(api, "usedBy").mockResolvedValue({ used_by: USED });
    render(<Rows idents={["invented_product", "unused_product"]} />);
    const used = await screen.findByLabelText("invented_product");
    expect(used.textContent).toBe("Used by: Invented offer, Invented renewal");
    expect(within(used).getByRole("link", { name: "Invented offer" }).getAttribute("href"))
      .toBe(routeHash({ view: "settings", section: "processes", item: "invented_offer" }));
    expect(screen.getByLabelText("unused_product").textContent).toBe("No process uses it");
    expect(asked).toHaveBeenCalledTimes(1);
    expect(asked).toHaveBeenCalledWith("product");
  });

  it("the partner register names the processes of the chosen role", async () => {
    const roles: PartnerRoles = { customer: { label: "Customer", what: "Asks for a quote" }, broker: { label: "Broker", what: "Brings a case" } };
    vi.spyOn(api, "partners").mockResolvedValue({ partners: [], roles });
    vi.spyOn(api, "partnerSuggestions").mockResolvedValue({ suggestions: [] } as never);
    vi.spyOn(api, "usedBy").mockResolvedValue({ used_by: { customer: [{ id: "invented_quote", title: "Invented quote" }] } });
    render(<PartnersPanel />);
    const role = (await screen.findByLabelText("Role")) as HTMLSelectElement;
    expect(screen.queryByText(/Used by:/)).toBeNull();
    fireEvent.change(role, { target: { value: "customer" } });
    expect((await screen.findByRole("link", { name: "Invented quote" })).closest("p")?.textContent).toBe("Used by: Invented quote");
    fireEvent.change(role, { target: { value: "broker" } });
    expect(await screen.findByText("No process uses it")).toBeTruthy();
  });

  it("has its words in Hungarian", () => {
    const hu = hungarian as Record<string, string>;
    for (const key of ["Used by", "Used by:", "No process uses it"]) expect(hu[key]).toBeTruthy();
  });
});
