// 066 Á21: the active user („Ki dolgozik?”, Who is working?) lives in the browser's shared storage. If it is changed in
// another tab, this tab's actions already go out under the new name; the display must update too, otherwise the tab
// shows something other than what it uses.
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
      localStorage.setItem("jav.actor", "Teszt Elek"); // the other tab's write
      window.dispatchEvent(new StorageEvent("storage", { key: "jav.actor", newValue: "Teszt Elek" }));
    });
    expect(screen.getByTestId("who").textContent).toBe("Teszt Elek");
  });
});
