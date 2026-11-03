// 279 (the owner's decisions of 2026-11-02): Azure Document Intelligence on the Operations page and under the
// processing settings — set up or not on this machine, switched off, the last free check, and the check itself.
// Artificial data, no service.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type AzureInfo, type Recipe } from "./api";
import { setLanguage } from "./i18n";
import { AzurePanel, AzureSettingNotice, azureOn, azureState, checkReason } from "./views/settings/AzurePanel";

afterEach(async () => { vi.restoreAllMocks(); await setLanguage("hu"); });

const info = (over: Partial<AzureInfo> = {}): AzureInfo => ({
  configured: true, enabled: true, host: "example-di.cognitiveservices.azure.com", model: "prebuilt-read",
  api_version: "2024-11-30", max_pages: 12, usd_per_page: "0.0015", escalation: true,
  last_check: { at: "2026-11-02T10:00:00+00:00", ok: true, reason: null, host: "example-di.cognitiveservices.azure.com" },
  ...over,
});

describe("279 Azure recognition on this machine", () => {
  it("says each state in one sentence", () => {
    expect(azureState(info())).toMatchObject({ level: "ok" });
    expect(azureState(info()).text).toMatch(/be van állítva, és válaszol \(example-di/);
    expect(azureState(info({ configured: false, host: null, last_check: null })).text).toMatch(/nincs beállítva.*teendővel/);
    expect(azureState(info({ enabled: false })).text).toMatch(/ki van kapcsolva/);
    expect(azureState(info({ last_check: null }))).toMatchObject({ level: "warn" });
    const failed = azureState(info({ last_check: { at: "2026-11-02T10:00:00+00:00", ok: false, reason: "refused_key", host: null } }));
    expect(failed.level).toBe("error");
    expect(failed.text).toMatch(/elutasította a kulcsot/);
    expect(checkReason("http_503")).toMatch(/hibával válaszolt \(503\)/);
  });

  it("draws the card and runs the free check, in English too", async () => {
    vi.spyOn(api, "azure").mockResolvedValue(info({ last_check: null }));
    const check = vi.spyOn(api, "azureCheck").mockResolvedValue({ at: "2026-11-02T10:00:00+00:00", ok: true, reason: null, host: "x" });
    await setLanguage("en");
    render(<AzurePanel />);
    expect((await screen.findByRole("status")).textContent).toMatch(/set up \(example-di.*not been checked yet/);
    expect(screen.getByText(/at most 12 pages per document · about 0\.0015 USD per page/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Check now (free)" }));
    await waitFor(() => expect(check).toHaveBeenCalledTimes(1));
  });

  it("offers no check where Azure is not set up", async () => {
    vi.spyOn(api, "azure").mockResolvedValue(info({ configured: false, host: null, last_check: null }));
    render(<AzurePanel />);
    expect((await screen.findByRole("status")).textContent).toMatch(/nincs beállítva/);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("warns under the processing settings only when Azure is on and cannot run here", async () => {
    vi.spyOn(api, "azure").mockResolvedValue(info({ configured: false, host: null, last_check: null }));
    const { rerender } = render(<AzureSettingNotice on={true} />);
    expect((await screen.findByRole("note")).textContent).toMatch(/nincs beállítva.*Üzemeltetés/);
    rerender(<AzureSettingNotice on={false} />);
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("reads the setting from the saved value or the recipe's default", () => {
    const recipe = { params: { azure_ocr: { allowed: ["on", "off"], default: "on" } } } as unknown as Recipe;
    expect(azureOn(recipe, {})).toBe(true);
    expect(azureOn(recipe, { azure_ocr: "off" })).toBe(false);
    expect(azureOn({ params: {} } as unknown as Recipe, {})).toBe(false);
  });
});
