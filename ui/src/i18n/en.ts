/// <reference types="vite/client" />
// The English dictionary: every `en-*.json` in one object (a separate file per area, so that they can be extended in
// parallel). Loaded only when switching to English (the dynamic import in `setLanguage("en")`).
import type { Messages } from "./index";

const parts = import.meta.glob<Messages>("./en-*.json", { eager: true, import: "default" });
const english: Messages = Object.assign({}, ...Object.keys(parts).sort().map((k) => parts[k]));
export default english;
