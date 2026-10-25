// 081 (the owner's trial of 2026-10-01): a package from a folder can take its subfolders too („Almappák is”, off by
// default), and every path field has a „Tallózás…” (Browse…) button that opens the operating system's own picker
// through the local service. Artificial data, no service.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, type WorkflowTemplates } from "./api";
import { BrowseButton } from "./components/BrowseButton";
import { CreateForm } from "./views/Workpackages";
import workflowConfig from "./views/workflows/workflowTemplates181.fixture.json";

afterEach(() => vi.restoreAllMocks());

// 231 (C3b5a): the documents' one-step template is its process pack's case, started with the general form
const PACKS = { processes: [{ id: "documents", title: "Documents", version: "1.0.0", scope: ["source"], asks: ["source"],
  package_kinds: [] }] };
function mockCaseStart() {
  vi.spyOn(api, "workflowTemplates").mockResolvedValue(workflowConfig as unknown as WorkflowTemplates);
  vi.spyOn(api, "processes").mockResolvedValue(PACKS);
  vi.spyOn(api, "workpackagesBrief").mockResolvedValue({ workpackages: [] } as never);
  vi.spyOn(api, "parties").mockResolvedValue({ parties: [] } as never);
  return vi.spyOn(api, "startCase").mockResolvedValue({ case_id: "wp-1" });
}

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
    const start = mockCaseStart();
    const onDone = vi.fn();
    const user = userEvent.setup();
    render(<CreateForm onDone={onDone} initialTemplate="documents" />);
    const sub = await screen.findByRole("checkbox", { name: "Az almappái is" }) as HTMLInputElement; // 195: the form loads on first use
    expect(sub.checked).toBe(false);
    await user.click(screen.getByRole("button", { name: "Tallózás…" }));
    await waitFor(() => expect((screen.getByLabelText("A mappa teljes útvonala") as HTMLInputElement).value).toBe("C:\\szamlak"));
    await user.click(sub);
    await user.click(screen.getByRole("button", { name: "Létrehozás" }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith("wp-1"));
    expect(start.mock.calls[0][0].source).toEqual({ kind: "folder", folder: "C:\\szamlak", recursive: true });
  });

  it("the file picker appends the chosen files to the existing lines without repeats, a pasted path without its quotes", async () => {
    vi.spyOn(api, "pickFiles").mockResolvedValue({ paths: ["C:\\a\\1.pdf", "C:\\b\\2.pdf"] });
    mockCaseStart();
    const user = userEvent.setup();
    render(<CreateForm onDone={vi.fn()} initialTemplate="documents" />);
    await user.click(await screen.findByRole("radio", { name: "Megadott fájlok" }));
    const box = screen.getByLabelText("A fájlok teljes útvonala, soronként egy") as HTMLTextAreaElement;
    await user.type(box, "\"C:\\a\\1.pdf\"");
    await user.click(screen.getByRole("button", { name: "Tallózás…" }));
    await waitFor(() => expect(box.value).toBe("C:\\a\\1.pdf\nC:\\b\\2.pdf"));
  });
});
