export interface MessageSummary {
  id: string;
  from: string;
  subject: string;
  date: string | null;
  unread: boolean;
  category: string | null;
  snippet: string;
}

export interface QuerySource {
  id: string;
  from: string;
  subject: string;
  date: string | null;
}

export interface QueryResponse {
  answer: string;
  sources: QuerySource[];
}

export interface DigestResponse {
  id: string;
  generated_at: string;
  unread_count: number;
  content_markdown: string;
}

export interface Category {
  name: string;
  description: string;
}

export interface Label {
  id: string;
  name: string;
}

export interface ProposeResponse {
  proposal_id: string;
  action: string;
  expires_at: string;
  affected_count: number;
  affected: MessageSummary[];
}

export interface ActionResult {
  action: string;
  message_count: number;
  message_ids: string[];
}

export type ActionType =
  | "mark_read"
  | "mark_unread"
  | "star"
  | "unstar"
  | "archive"
  | "trash"
  | "add_label"
  | "remove_label";

export interface SearchParams {
  q: string;
  category?: string;
  sender?: string;
  after?: string;
  before?: string;
  unread_only?: boolean;
  limit?: number;
}

export type JobStatus =
  | "applied"
  | "acknowledged"
  | "interview"
  | "moving_forward"
  | "offer"
  | "rejected"
  | "other";

export interface JobApplication {
  id: string;
  company: string;
  role: string | null;
  status: JobStatus;
  status_updated_at: string;
  event_count: number;
}

export interface JobApplicationEvent {
  id: string;
  event_type: JobStatus;
  event_date: string;
  summary: string;
  source_message: MessageSummary | null;
}

export interface JobApplicationDetail extends JobApplication {
  events: JobApplicationEvent[];
}
