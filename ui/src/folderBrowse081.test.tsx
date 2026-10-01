// 081 (the owner's trial of 2026-10-01): a package from a folder can take its subfolders too („Almappák is”, off by
// default), and every path field has a „Tallózás…” (Browse…) button that opens the operating system's own picker
// through the local service. Artificial data, no service.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, type Readiness, type Workpackage } from "./api";
import { BrowseButton } from "./components/BrowseButton";
import { CreateForm } from "./views/Workpackages";

afterEach(() => vi.restoreAllMocks());

const CREATED = { workpackage: { id: "wp-1" } as Workpackage, readiness: {} as Readiness };

describe("081 browsing", () => {
  it("the folder picker starts from the field's current value and returns the chosen folder", async () => {
    const pick = vi.spyOn(api, "pickFolder").mockResolvedValue({ path: "C:\\szamlak\\2026" });
    const onPick = vi.fn();
    render(<BrowseButton kind="folder" initial={"C:\\szamlak"} onPick={onPick} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Tallózás…" }));
    await waitFor(() => expect(onPick).toHaveBeenCalledWith(["C:\\szamlak\\2026"]));
    expect(pick).toHaveBeenCalledWith("Mappa kiválasztása", "C:\\szamlak");
  });

  it("a cancelled pick changes nothing", async () => {
    vi.spyOn(api, "pickFolder").mockResolvedValue({ path: null });
    const onPick = vi.fn();
    render(<BrowseButton kind="folder" onPick={onPick} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Tallózás…" }));
    await waitFor(() => expect((screen.getByRole("button", { name: "Tallózás…" }) as HTMLButtonElement).disabled).toBe(false));
    expect(onPick).not.toHaveBeenCalled();
  });

  it("when no picker can open here, it asks for the path to be typed", async () => {
    vi.spyOn(api, "pickFiles").mockRejectedValue(new ApiError(503, "picker_unavailable", "no display"));
    render(<BrowseButton kind="files" onPick={vi.fn()} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Tallózás…" }));
    expect((await screen.findByRole("alert")).textContent).toBe("A választó ablak itt nem nyitható meg; írd be az útvonalat.");
  });
});

describe("081 package from a folder", () => {
  it("subfolders are left out by default; ticked, the service is asked for them too", async () => {
    vi.spyOn(api, "pickFolder").mockResolvedValue({ path: "C:\\szamlak" });
    const create = vi.spyOn(api, "createFromFolder").mockResolvedValue(CREATED);
    const onDone = vi.fn();
    const user = userEvent.setup();
    render(<CreateForm onDone={onDone} />);
    const sub = screen.getByRole("checkbox", { name: "Almappák is" }) as HTMLInputElement;
    expect(sub.checked).toBe(false);
    await user.click(screen.getByRole("button", { name: "Tallózás…" }));
    await waitFor(() => expect((screen.getByLabelText("Mappa teljes útvonala") as HTMLInputElement).value).toBe("C:\\szamlak"));
    await user.click(sub);
    await user.click(screen.getByRole("button", { name: "Létrehozás" }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith("wp-1"));
    expect(create).toHaveBeenCalledWith("C:\\szamlak", undefined, true);
  });

  it("the file picker appends the chosen files to the existing lines without repeats", async () => {
    vi.spyOn(api, "pickFiles").mockResolvedValue({ paths: ["C:\\a\\1.pdf", "C:\\b\\2.pdf"] });
    const user = userEvent.setup();
    render(<CreateForm onDone={vi.fn()} />);
    await user.click(screen.getByRole("radio", { name: "Megadott fájlok" }));
    const box = screen.getByLabelText("Fájlok teljes útvonala, soronként egy") as HTMLTextAreaElement;
    await user.type(box, "C:\\a\\1.pdf");
    await user.click(screen.getByRole("button", { name: "Tallózás…" }));
    await waitFor(() => expect(box.value).toBe("C:\\a\\1.pdf\nC:\\b\\2.pdf"));
  });
});
