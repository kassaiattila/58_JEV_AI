// 066 Á21: az aktív felhasználó („Ki dolgozik?”) a böngésző közös tárolójában van. Ha egy másik lapon átállítják, ennek
// a lapnak a műveletei már az új névvel mennek; a kijelzés is frissüljön, különben a lap mást mutat, mint amit használ.
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { setActor } from "./api";
import { useActor } from "./hooks";

function Who() {
  return <span data-testid="who">{useActor()}</span>;
}

afterEach(() => setActor(""));

describe("Aktív felhasználó több lapon (066 Á21)", () => {
  it("egy másik lapon végzett váltás ezen a lapon is látszik", () => {
    setActor("Minta Anna");
    render(<Who />);
    expect(screen.getByTestId("who").textContent).toBe("Minta Anna");
    act(() => {
      localStorage.setItem("jav.actor", "Teszt Elek"); // a másik lap írása
      window.dispatchEvent(new StorageEvent("storage", { key: "jav.actor", newValue: "Teszt Elek" }));
    });
    expect(screen.getByTestId("who").textContent).toBe("Teszt Elek");
  });
});
