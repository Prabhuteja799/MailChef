import { loadConfig } from "./config";
import type {
  ActionResult,
  Category,
  DigestResponse,
  JobApplication,
  JobApplicationDetail,
  Label,
  MessageSummary,
  ProposeResponse,
  QueryResponse,
  SearchParams,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const config = loadConfig();
  if (!config) throw new ApiError("Not configured", 0);

  const headers: Record<string, string> = { Authorization: `Bearer ${config.apiToken}` };
  if (init?.body) headers["Content-Type"] = "application/json";

  const res = await fetch(`${config.backendUrl}${path}`, { ...init, headers });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // response wasn't JSON — fall back to statusText
    }
    throw new ApiError(String(detail), res.status);
  }
  return (await res.json()) as T;
}

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const s = search.toString();
  return s ? `?${s}` : "";
}

export const api = {
  health: () => request<{ status: string }>("/health"),

  query: (question: string) =>
    request<QueryResponse>("/query", { method: "POST", body: JSON.stringify({ question }) }),

  search: (params: SearchParams) =>
    request<MessageSummary[]>(`/search${qs(params as unknown as Record<string, string | number | boolean | undefined>)}`),

  categories: () => request<Category[]>("/categories"),
  labels: () => request<Label[]>("/labels"),

  digestLatest: () => request<DigestResponse>("/digest/latest"),
  digestRun: (sinceDays?: number) =>
    request<{ digest: DigestResponse }>(`/digest/run${qs({ since_days: sinceDays })}`, { method: "POST" }),

  syncRun: () => request<Record<string, unknown>>("/sync/run", { method: "POST" }),
  classifyRun: () => request<Record<string, unknown>>("/classify/run", { method: "POST" }),
  indexRun: () => request<Record<string, unknown>>("/index/run", { method: "POST" }),

  actionsPropose: (body: Record<string, unknown>) =>
    request<ProposeResponse>("/actions/propose", { method: "POST", body: JSON.stringify(body) }),
  actionsConfirm: (proposalId: string) =>
    request<ActionResult>("/actions/confirm", { method: "POST", body: JSON.stringify({ proposal_id: proposalId }) }),
  actionsCancel: (proposalId: string) =>
    request<{ cancelled: boolean }>("/actions/cancel", { method: "POST", body: JSON.stringify({ proposal_id: proposalId }) }),
  actionsExecute: (body: Record<string, unknown>) =>
    request<ActionResult>("/actions/execute", { method: "POST", body: JSON.stringify(body) }),

  jobsList: () => request<JobApplication[]>("/jobs"),
  jobsDetail: (id: string) => request<JobApplicationDetail>(`/jobs/${id}`),
  jobsExtract: (sinceDays?: number) =>
    request<Record<string, unknown>>(`/jobs/extract${qs({ since_days: sinceDays })}`, { method: "POST" }),
};
