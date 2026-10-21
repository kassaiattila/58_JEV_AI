// 195 (plan G-tidy R5): a rarely used page loads its code only when it is first shown, so the main bundle the browser
// reads on every start stays small: the settings, the workflows, a person's day, the old result addresses, the new work
// wizard and each logic pack's own pages. Until the code arrives, the page shows the same loading line as a page whose
// data is on its way. A page whose code cannot be loaded (e.g. an open tab after a new build replaced the files) fails
// into the view's error boundary, which offers a reload, as the update banner does.
import { lazy, Suspense, type ComponentType } from "react";
import { t } from "../i18n";

/** A component whose module is imported on first render; `load` picks the named export, e.g.
 *  `lazyPage(() => import("../views/Settings").then((m) => m.Settings))`. */
export function lazyPage<P extends object>(load: () => Promise<ComponentType<P>>): ComponentType<P> {
  const Page = lazy(async () => ({ default: await load() }));
  return function LazyPage(props: P) {
    return (
      <Suspense fallback={<p className="muted">{t("Loading…")}</p>}>
        <Page {...props} />
      </Suspense>
    );
  };
}
