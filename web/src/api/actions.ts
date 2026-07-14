import { ApiError, api } from "./client";
import type { ActionType, ProposeResponse } from "./types";

export interface ActionRequestBody {
  action: ActionType;
  message_ids?: string[];
  search?: string;
  category?: string;
  sender?: string;
  after?: string;
  before?: string;
  unread_only?: boolean;
  limit?: number;
  label_name?: string;
}

export interface RunActionOptions {
  /** archive/trash always confirm regardless of target count, matching the backend/CLI rule. */
  alwaysConfirm?: boolean;
  /** Shows the affected emails and resolves true/false based on the user's choice. */
  confirm: (proposal: ProposeResponse) => Promise<boolean>;
}

/**
 * Single explicit id + a safe action -> executes immediately. Anything else
 * (bulk, search-resolved, or archive/trash) -> propose, show the affected
 * emails via opts.confirm, and only confirm if the user says yes. Mirrors
 * cli/mailchef_cli/actions.py's run_action so the CLI and web UI enforce the
 * same confirmation guarantees.
 */
export async function runAction(body: ActionRequestBody, opts: RunActionOptions): Promise<void> {
  const singleExplicit = !body.search && body.message_ids?.length === 1;

  if (!opts.alwaysConfirm && singleExplicit) {
    try {
      await api.actionsExecute(body as unknown as Record<string, unknown>);
      return;
    } catch (e) {
      if (!(e instanceof ApiError) || e.status !== 400) throw e;
      // Backend says this needs confirmation after all — fall through to propose/confirm.
    }
  }

  const proposal = await api.actionsPropose(body as unknown as Record<string, unknown>);
  if (proposal.affected_count === 0) return;

  const confirmed = await opts.confirm(proposal);
  if (confirmed) {
    await api.actionsConfirm(proposal.proposal_id);
  } else {
    await api.actionsCancel(proposal.proposal_id);
  }
}
