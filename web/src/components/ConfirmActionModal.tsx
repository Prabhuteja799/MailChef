import type { ProposeResponse } from "../api/types";

interface Props {
  proposal: ProposeResponse;
  onConfirm: () => void;
  onCancel: () => void;
  busy: boolean;
}

export function ConfirmActionModal({ proposal, onConfirm, onCancel, busy }: Props) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <div className="modal">
        <h3>
          {proposal.action} {proposal.affected_count} email{proposal.affected_count === 1 ? "" : "s"}?
        </h3>
        <div className="modal-list">
          {proposal.affected.map((m) => (
            <div className="modal-list-row" key={m.id}>
              <div className="modal-list-from">{m.from}</div>
              <div className="modal-list-subject">{m.subject}</div>
              <div className="modal-list-date muted">{m.date ? m.date.slice(0, 10) : ""}</div>
            </div>
          ))}
        </div>
        <div className="modal-actions">
          <button className="secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button className="danger" onClick={onConfirm} disabled={busy}>
            {busy ? "Working…" : `Yes, ${proposal.action}`}
          </button>
        </div>
      </div>
    </div>
  );
}
