// Client of the local service (jav/service/api.py), split by theme (202, plan G-core-generalisation M3c): the connection
// (client.ts), the shared records and calls, and each domain's own (finance, quotes, email). `api` puts every
// theme's calls together, so a caller keeps using `api.<call>`. 231 (C3e): a domain's calls and records live in its
// folder (`ui/src/domains/<domain>/api.ts`); the domain adds its calls to `api` when the interface loads
// (`registerCalls`) and their types by declaration merging (`DomainCalls`), so the shared code imports none.
export * from "./types";
export * from "./work";
export * from "./workflows";
export * from "./outputs";
export * from "./datasets";
export * from "./system";
export * from "./finance";
export * from "./email";
export * from "./cases";
export * from "./partners";
export * from "./processes";
export { ACTOR_EVENT, ApiError, filenameFromDisposition, type UploadCheck, type UploadChecks, getActor, NO_ACTOR, READ_TIMEOUT_MS, setActor, UNKNOWN_ACTOR, USERS_EVENT } from "./client";
import { workApi } from "./work";
import { workflowsApi } from "./workflows";
import { outputsApi } from "./outputs";
import { datasetsApi } from "./datasets";
import { systemApi } from "./system";
import { financeApi } from "./finance";
import { emailApi } from "./email";
import { casesApi } from "./cases";
import { partnersApi } from "./partners";
import { processesApi } from "./processes";

const shared = {
  ...workApi,
  ...workflowsApi,
  ...outputsApi,
  ...datasetsApi,
  ...systemApi,
  ...financeApi,
  ...emailApi,
  ...casesApi,
  ...partnersApi,
  ...processesApi,
};

/** 231 (C3e): the calls the domains add (`registerCalls`); each domain merges its calls' types into this interface. */
export interface DomainCalls {}

export const api = shared as typeof shared & DomainCalls;

/** Adds a domain's calls to `api` (a domain's `index.tsx`, when the interface loads). */
export function registerCalls(calls: object): void {
  Object.assign(api, calls);
}
