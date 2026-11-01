// 265 (code review UI-14; the owner's decision: ESLint as a pinned development dependency, run by preflight): the
// interface's code check. The recommended JavaScript and TypeScript rules and React's two hook rules: a hook is called
// the same way on every render, and an effect names what it reads (a deliberate exception says why, beside it).
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/**", "node_modules/**", "runs/**"] },
  // a disable comment that no longer suppresses anything fails, so an exception never outlives its reason
  { linterOptions: { reportUnusedDisableDirectives: "error" } },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}", "vite.config.ts"],
    plugins: { "react-hooks": reactHooks },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",
      // a name left out on purpose starts with an underscore (`const { id: _id, ...rest } = row`)
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_",
        caughtErrorsIgnorePattern: "^_", ignoreRestSiblings: true }],
      // a domain's calls merge into the shared interface by extending it (`interface DomainCalls extends EmailCalls {}`)
      "@typescript-eslint/no-empty-object-type": ["error", { allowInterfaces: "with-single-extends" }],
    },
  },
  {
    files: ["scripts/**/*.mjs"],
    languageOptions: { globals: { console: "readonly", process: "readonly" } },
  },
);
