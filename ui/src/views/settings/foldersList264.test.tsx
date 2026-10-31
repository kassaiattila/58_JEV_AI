// 264 (plan E, F6; the owner's decision of 2026-10-31: the small lists the one list too): Settings › Work folders is the one
// list, each folder opening its own page; "Add work folder" is the title row's main action with a page of its own; a
// folder's page saves it with the rest of the list as it was read, and removes it there (asking first). Synthetic
// folders, a mocked service.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor, type WatchedFolder } from "../../api";
import { findConfirmAction } from "../../confirm.testutil";
import { setLanguage } from "../../i18n";
import hungarian from "../../i18n/hu-native.json";
import { linkCol, listPage } from "./listPage.testutil";
import { FoldersPanel } from "./FoldersPanel";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic owner"); sessionStorage.clear(); window.location.hash = ""; });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const A: WatchedFolder = { id: "wf-0000000001", name: "Incoming", path: "D:\\Synthetic\\in", enabled: true, recursive: false,
  batch_mode: "folder", recipe_id: null, params: {}, interval_min: 15 };
const B: WatchedFolder = { ...A, id: "wf-0000000002", name: "Scans", path: "D:\\Synthetic\\scans" };

describe("Settings › Work folders", () => {
  it("lists the folders, each opening its page, with Add work folder in the title row", async () => {
    vi.spyOn(api, "outputFolder").mockResolvedValue({ path: null });
    vi.spyOn(api, "datasetQuery").mockResolvedValue(listPage("settings_folders", [linkCol("name", "Name", "folders")],
      [{ _key: A.id!, name: A.name }]));
    render(<FoldersPanel />);
    expect(screen.getByRole("link", { name: "Add work folder" }).getAttribute("href")).toBe("#/settings/folders/new");
    const table = await screen.findByRole("table", { name: "Work folders" });
    expect(within(table).getByRole("link", { name: "Incoming" }).getAttribute("href")).toBe("#/settings/folders/wf-0000000001");
  });

  it("saves a folder with the rest of the list as it was read, and removes it on its page", async () => {
    vi.spyOn(api, "folders").mockResolvedValue({ folders: [A, B], roots: [] });
    const save = vi.spyOn(api, "saveFolders").mockImplementation(async (folders) => ({ folders, roots: [] }));
    render(<FoldersPanel item="wf-0000000001" />);
    const sheet = await screen.findByRole("region", { name: "Incoming" });
    fireEvent.click(within(sheet).getByRole("checkbox", { name: "Include subfolders" }));
    fireEvent.click(within(sheet).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(save).toHaveBeenLastCalledWith([{ ...A, recursive: true }, B]));
    fireEvent.click(within(sheet).getByRole("button", { name: "Remove" }));
    fireEvent.click(await findConfirmAction());
    await waitFor(() => expect(save).toHaveBeenLastCalledWith([B]));
    await waitFor(() => expect(window.location.hash).toBe("#/settings/folders"));
  });

  it("adds a new folder on its own page and opens it", async () => {
    vi.spyOn(api, "folders").mockResolvedValue({ folders: [A], roots: [] });
    const save = vi.spyOn(api, "saveFolders").mockResolvedValue({ folders: [A, { ...B, id: "wf-0000000003" }], roots: [] });
    render(<FoldersPanel item="new" />);
    const sheet = await screen.findByRole("region", { name: "New work folder" });
    fireEvent.change(within(sheet).getByLabelText("Full folder path"), { target: { value: "D:\\Synthetic\\scans" } });
    fireEvent.click(within(sheet).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(save).toHaveBeenCalledWith([A, expect.objectContaining({ path: "D:\\Synthetic\\scans" })]));
    await waitFor(() => expect(window.location.hash).toBe("#/settings/folders/wf-0000000003"));
  });

  it("has its words in Hungarian", () => {
    const hu = hungarian as Record<string, string>;
    for (const key of ["No work folder yet: “Add work folder” sets one.", "It is not among the work folders (any more).",
      "Remove this work folder? Its batches and documents stay; the worker no longer checks it.", "Last check", "Its outcome",
      "New documents", "every 5 minutes"]) {
      expect(hu[key], key).toBeTruthy();
      expect(hu[key]).not.toBe(key);
    }
  });
});
