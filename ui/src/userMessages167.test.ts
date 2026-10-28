// 167 (review 160 U-1): an error the service sends with its English template and parameters is shown in the chosen
// language, like the interface's own labels; a message without a template is shown as it is.
import { afterEach, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";
import { setLanguage } from "./i18n";

afterEach(async () => { vi.restoreAllMocks(); await setLanguage("hu"); });

function failWith(body: unknown, status = 422) {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(body), { status }));
}

async function caught(): Promise<ApiError> {
  try {
    await api.workpackage("wp-1");
  } catch (e) {
    return e as ApiError;
  }
  throw new Error("no error");
}

it("a templated message is translated with its parameters", async () => {
  failWith({ error: "invalid", message: "Documents to add: their full paths, one per line", template: "In the package: {{items}}",
    params: { items: "3 irat" } });
  const err = await caught();
  expect(err.message).toBe("A kötegben: 3 irat");
  expect(err.code).toBe("invalid");
  expect(err.status).toBe(422);
});

it("in English the template is filled as it is", async () => {
  await setLanguage("en");
  failWith({ error: "not_ready", message: "x", template: "In the package: {{items}}", params: { items: "3 documents" }, blockers: [] }, 409);
  expect((await caught()).message).toBe("In the batch: 3 documents");
});

it("a message without a template is shown as the service wrote it", async () => {
  failWith({ error: "invalid", message: "plain text from the service" });
  expect((await caught()).message).toBe("plain text from the service");
});
