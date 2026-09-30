// 066 Á36: an unexpected error in a view does not leave an empty page; a message and a reload button appear.
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./components/ErrorBoundary";

afterEach(() => vi.restoreAllMocks());

function Broken(): never {
  throw new Error("kitalált hiba");
}

describe("Hibahatár (066 Á36)", () => {
  it("üzenetet és újratöltés-gombot mutat üres oldal helyett", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(<ErrorBoundary><Broken /></ErrorBoundary>);
    expect(screen.getByRole("heading").textContent).toBe("Váratlan hiba a felületen");
    expect(screen.getByRole("button", { name: "Újratöltés" })).toBeTruthy();
    expect(screen.getByText("kitalált hiba")).toBeTruthy();
  });
});
