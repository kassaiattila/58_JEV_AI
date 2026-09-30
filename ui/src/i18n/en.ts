/// <reference types="vite/client" />
// Az angol szótár: az összes `en-*.json` egy objektumban (területenként külön fájl, hogy párhuzamosan bővíthető legyen).
// Csak angolra váltáskor töltődik be (`setLanguage("en")` dinamikus importja).
import type { Messages } from "./index";

const parts = import.meta.glob<Messages>("./en-*.json", { eager: true, import: "default" });
const english: Messages = Object.assign({}, ...Object.keys(parts).sort().map((k) => parts[k]));
export default english;
