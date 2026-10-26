import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";
import { resetWork } from "./components/editing";
import "./domains"; // 231 (C3e): the domains register their screens, as at the interface's start (main.tsx)

// 149: under the load of a full check a slow render can take longer than the default 1 s of `findBy*` and `waitFor`,
// and a test failed now and then. A real failure still fails, only later.
configure({ asyncUtilTimeout: 5000 });

// D0-g: an editor's unsaved work lives in the page's memory; each test starts with none
afterEach(() => { cleanup(); resetWork(); });
