// 078: content-named copies — the Result view's ZIP link and write button, and the output folder in Settings (saved on
// its own; an overlap with a watched folder is named in the display language).
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, setActor } from "./api";
import { NamedCopiesBar } from "./views/ResultStage";
import { OutputFolderCard } from "./views/settings/FoldersPanel";

beforeEach(() => setActor("Minta Anna"));
afterEach(() => vi.restoreAllMocks());

describe("078 named copies in the Result section", () => {
  it("offers the ZIP and writes into the output folder", async () => {
    vi.spyOn(api, "outputFolder").mockResolvedValue({ path: "D:\\Archivum" });
    const write = vi.spyOn(api, "writeNamedCopies").mockResolvedValue({ path: "D:\\Archivum\\Csomag_run-1", ready: 3, review: 1, skipped: 0 });
    render(<NamedCopiesBar runId="run-1" />);
    expect(screen.getByRole("link", { name: /Letöltés ZIP-ben/ }).getAttribute("href")).toBe("/api/runs/run-1/named-copies.zip");
    const button = screen.getByRole("button", { name: "Kiírás a kimeneti mappába" });
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(button);
    await waitFor(() => expect(write).toHaveBeenCalledWith("run-1"));
    expect((await screen.findByRole("status")).textContent).toMatch(/3 kész, 1 ellenőrzendő, 0 kimaradt/);
  });

  it("points to Settings when there is no output folder", async () => {
    vi.spyOn(api, "outputFolder").mockResolvedValue({ path: null });
    render(<NamedCopiesBar runId="run-1" />);
    expect((await screen.findByRole("link", { name: "Beállítások › Munkamappák" })).getAttribute("href")).toBe("#/settings/folders");
    expect((screen.getByRole("button", { name: "Kiírás a kimeneti mappába" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("078 output folder in Settings", () => {
  it("keeps what was typed before the saved value arrived", async () => {
    let arrive: (v: { path: string | null }) => void = () => {};
    vi.spyOn(api, "outputFolder").mockReturnValue(new Promise((ok) => { arrive = ok; }));
    render(<OutputFolderCard />);
    const input = screen.getByLabelText(/Mappa teljes útvonala/) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "D:\\Uj" } });
    arrive({ path: "D:\\Regi" });
    await waitFor(() => expect((screen.getByRole("button", { name: "Mentés" }) as HTMLButtonElement).disabled).toBe(false));
    expect(input.value).toBe("D:\\Uj");
  });

  it("saves the path and names an overlap with a watched folder", async () => {
    vi.spyOn(api, "outputFolder").mockResolvedValue({ path: null });
    const save = vi.spyOn(api, "saveOutputFolder")
      .mockRejectedValueOnce(new ApiError(422, "folder_overlap", "the output folder cannot overlap the watched folder 'X'"))
      .mockResolvedValueOnce({ path: "D:\\Archivum" });
    render(<OutputFolderCard />);
    const input = await screen.findByLabelText(/Mappa teljes útvonala/);
    fireEvent.change(input, { target: { value: " D:\\Bejovo\\al " } });
    fireEvent.click(screen.getByRole("button", { name: "Mentés" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/figyelt munkamappa nem lehet egymásban/);
    expect(save).toHaveBeenCalledWith("D:\\Bejovo\\al");
    fireEvent.change(input, { target: { value: "D:\\Archivum" } });
    fireEvent.click(screen.getByRole("button", { name: "Mentés" }));
    expect((await screen.findByRole("status")).textContent).toBe("Mentve.");
  });
});
