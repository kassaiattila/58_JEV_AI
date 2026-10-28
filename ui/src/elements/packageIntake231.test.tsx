// 231 (stage U, U1; the walkthrough of 2026-10-28): a case started from a package's page is named with its process's
// title in the interface's language and the package's own name (the service's ready name has the English title). A
// mocked service.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor } from "../api";
import { setLanguage } from "../i18n";
import { PackageIntake } from "./ProcessStart";

beforeEach(async () => { await setLanguage("hu"); setActor("Minta Anna"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.location.hash = ""; });

describe("a package's offer of a case (231 U1)", () => {
  it("names the case in the interface's language", async () => {
    const start = vi.spyOn(api, "startCase").mockResolvedValue({ case_id: "wp-000000000c02" });
    render(<PackageIntake offers={[{ pack: "mail_routing", title: "Email routing", name: "Email routing: Iroda postafiók",
      package_name: "Iroda postafiók", sources: ["wp-000000000c01"], cases: [] }]} />);
    fireEvent.click(screen.getByRole("button", { name: "Ügy indítása" }));
    await waitFor(() => expect(start).toHaveBeenCalledWith({ pack: "mail_routing", name: "Levél-becsatornázás: Iroda postafiók",
      sources: ["wp-000000000c01"] }));
  });
});
