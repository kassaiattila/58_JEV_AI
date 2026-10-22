// Client of the local service (jav/api.py), split by theme (202, plan G-core-generalisation M3c): the connection
// (client.ts), the shared records and calls, and each domain's own (finance, quotes, email). `api` puts every
// theme's calls together, so a caller keeps using `api.<call>`.
export * from "./types";
export * from "./work";
export * from "./workflows";
export * from "./outputs";
export * from "./datasets";
export * from "./system";
export * from "./finance";
export * from "./quotes";
export * from "./email";
export { ACTOR_EVENT, ApiError, filenameFromDisposition, getActor, NO_ACTOR, READ_TIMEOUT_MS, setActor, UNKNOWN_ACTOR, USERS_EVENT } from "./client";
import { workApi } from "./work";
import { workflowsApi } from "./workflows";
import { outputsApi } from "./outputs";
import { datasetsApi } from "./datasets";
import { systemApi } from "./system";
import { financeApi } from "./finance";
import { quotesApi } from "./quotes";
import { emailApi } from "./email";

export const api = {
  ...workApi,
  ...workflowsApi,
  ...outputsApi,
  ...datasetsApi,
  ...systemApi,
  ...financeApi,
  ...quotesApi,
  ...emailApi,
};
