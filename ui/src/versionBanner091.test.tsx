// 091 (the version banner, the owner's decision of 2026-10-02: "yes, with a banner"): a tab left open for a
// long time showed the interface it had loaded before the service was restarted with new code. The tab now compares
// the service's state at page load with the state it checks later, and a banner asks for a reload when a newer version
// runs. Artificial data, no service; the interface runs in English so the test holds no Hungarian text.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { api, type Health } from "./api";
import { newerVersion, UpdateBanner } from "./components/UpdateBanner";
import { setLanguage } from "./i18n";

beforeAll(async () => { await setLanguage("en"); });
afterAll(async () => { await setLanguage("hu"); });
afterEach(() => vi.restoreAllMocks());

const health = (over: Partial<Health> = {}): Health => ({
  ok: true, api_version: "1", service_config: "1.9.0", version: "1.5.0", commit: "abc1234", dirty: false,
  started_at: "2026-10-02T10:00:00+00:00", ui_build: "aaaaaaaaaaaa", ...over,
});

describe("091 newer version check", () => {
  it("a different commit or UI build is a newer version", () => {
    expect(newerVersion(health(), health())).toBe(false);
    expect(newerVersion(health(), health({ commit: "def5678" }))).toBe(true);
    expect(newerVersion(health(), health({ ui_build: "bbbbbbbbbbbb" }))).toBe(true);
  });

  it("a restart of the same clean commit is not a newer version", () => {
    expect(newerVersion(health(), health({ started_at: "2026-10-02T12:00:00+00:00" }))).toBe(false);
  });

  it("a restart counts when the commit does not prove the code", () => {
    const later = { started_at: "2026-10-02T12:00:00+00:00" };
    expect(newerVersion(health({ dirty: true }), health({ dirty: true, ...later }))).toBe(true);
    expect(newerVersion(health({ commit: null, dirty: null }), health({ commit: null, dirty: null, ...later }))).toBe(true);
    expect(newerVersion(health({ dirty: true }), health({ dirty: true }))).toBe(false); // the same process
  });

  it("an older service without a UI build is judged by its commit", () => {
    expect(newerVersion(health({ ui_build: undefined }), health({ ui_build: undefined }))).toBe(false);
    expect(newerVersion(health({ ui_build: undefined }), health({ commit: "def5678" }))).toBe(true);
  });
});

describe("091 banner", () => {
  it("stays hidden while the version that loaded the page runs", async () => {
    const spy = vi.spyOn(api, "health").mockResolvedValue(health());
    render(<UpdateBanner pollMs={20} />);
    await waitFor(() => expect(spy.mock.calls.length).toBeGreaterThan(2));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("appears when the tab is shown again and a newer version runs, and reloads on request", async () => {
    const spy = vi.spyOn(api, "health").mockResolvedValueOnce(health()).mockResolvedValue(health({ commit: "def5678" }));
    render(<UpdateBanner pollMs={3600000} />);
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("status")).toBeNull();
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    const banner = await screen.findByRole("status");
    expect(banner.textContent).toMatch(/newer version/i);
    expect(banner.textContent).toMatch(/unsaved corrections are kept/i);
    const reload = vi.fn();
    vi.spyOn(window, "location", "get").mockReturnValue({ ...window.location, reload });
    fireEvent.click(screen.getByRole("button", { name: "Reload" }));
    expect(reload).toHaveBeenCalledTimes(1);
  });
});
