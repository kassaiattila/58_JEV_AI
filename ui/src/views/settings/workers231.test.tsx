// 231 (stage E, E1; the owner's decisions of 2026-10-29: several workers, one by default): Settings › Operations says how
// many of the allowed workers run when the service configuration allows more than one, and says nothing more when it
// allows one. A mocked service.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setActor } from "../../api";
import { setLanguage } from "../../i18n";
import hungarian from "../../i18n/hu-native.json";
import { Settings } from "../Settings";

beforeEach(async () => { await setLanguage("en"); setActor("Synthetic reviewer"); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("the workers on the Operations page (231 E1)", () => {
  it("says how many of the allowed workers run", async () => {
    vi.spyOn(api, "worker").mockResolvedValue({ running: true, workers: 2, slots: 3, stop_requested: false, jobs: { queued: 1 } });
    render(<Settings section="system" />);
    expect(await screen.findByText("2 of 3 workers")).toBeTruthy();
  });

  it("says nothing more when one worker is allowed", async () => {
    vi.spyOn(api, "worker").mockResolvedValue({ running: true, workers: 1, slots: 1, stop_requested: false, jobs: {} });
    render(<Settings section="system" />);
    await screen.findByText("Running");
    expect(screen.queryByText(/of 1 workers/)).toBeNull();
  });

  it("has its words in Hungarian", () => {
    expect((hungarian as Record<string, string>)["{{n}} of {{slots}} workers"]).toBeTruthy();
  });
});
