// 195 (plan G-tidy R6): the shared list of what holds a step back - a blocker or a warning per line, a reason with
// several lines grouped under its count, a line's parts side by side for the template and price list checks.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BlockerList, groupedBlockers } from "./components/BlockerList";

describe("the shared blocker list (195)", () => {
  it("marks a blocker and a warning by their own class, and names the list", () => {
    render(<BlockerList label="Gaps" parts items={[{ key: "a", content: "no customer" }, { key: "b", content: "an old rate", warning: true }]} />);
    const list = screen.getByRole("list", { name: "Gaps" });
    expect(list.className).toBe("plain template-issues");
    expect([...list.querySelectorAll(":scope > li")].map((li) => li.className)).toEqual(["blocker", "warning"]);
  });

  it("groups a reason with several lines under its count, in the order the reasons first occur", () => {
    const entries = [{ r: "late", n: 1 }, { r: "missing", n: 2 }, { r: "late", n: 3 }];
    const items = groupedBlockers(entries, (e) => e.r, (e) => ({ key: String(e.n), content: `line ${e.n}` }),
      (reason, n) => `${n} × ${reason}`);
    const { container } = render(<BlockerList small items={items} />);
    expect(screen.getByText("2 × late")).toBeTruthy();
    expect([...container.querySelectorAll("details li")].map((li) => li.textContent)).toEqual(["line 1", "line 3"]);
    expect(screen.getByText("line 2").className).toBe("blocker small"); // a reason with one line stays a line
  });
});
