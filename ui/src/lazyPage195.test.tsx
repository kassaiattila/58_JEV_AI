// 195 (plan G-tidy R5): a page loaded on first use shows the shared loading line until its code arrives, then the page
// with its props; a page whose code cannot be loaded fails into the view's error boundary, which offers a reload.
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { lazyPage } from "./components/LazyPage";
import { t } from "./i18n";

afterEach(() => vi.restoreAllMocks());

function Greeting({ name }: { name: string }) {
  return <h2>{`Hello, ${name}`}</h2>;
}

describe("a page loaded on first use (195)", () => {
  it("shows the loading line, then the page with its props", async () => {
    let arrive: (page: typeof Greeting) => void = () => {};
    const Page = lazyPage(() => new Promise<typeof Greeting>((resolve) => { arrive = resolve; }));
    render(<Page name="Invented Reader" />);
    expect(screen.getByText(t("Loading…"))).toBeTruthy();
    arrive(Greeting);
    expect((await screen.findByRole("heading")).textContent).toBe("Hello, Invented Reader");
    expect(screen.queryByText(t("Loading…"))).toBeNull();
  });

  it("loads its code once, however often it is shown", async () => {
    const load = vi.fn(async () => Greeting);
    const Page = lazyPage(load);
    const { unmount } = render(<Page name="first" />);
    await screen.findByRole("heading");
    unmount();
    render(<Page name="second" />);
    expect((await screen.findByRole("heading")).textContent).toBe("Hello, second");
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("fails into the error boundary when its code cannot be loaded", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const Page = lazyPage<{ name: string }>(() => Promise.reject(new Error("invented missing chunk")));
    render(<ErrorBoundary view><Page name="x" /></ErrorBoundary>);
    expect(await screen.findByText("invented missing chunk")).toBeTruthy();
  });
});
