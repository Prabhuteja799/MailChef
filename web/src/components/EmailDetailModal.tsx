import type { MessageDetail } from "../api/types";

interface Props {
  message: MessageDetail;
  onClose: () => void;
  onAction: (action: "mark_read" | "mark_unread" | "star" | "unstar" | "archive" | "trash") => void;
}

export function EmailDetailModal({ message, onClose, onAction }: Props) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="modal email-modal" onClick={(e) => e.stopPropagation()}>
        <div className="email-modal-header">
          <h3 style={{ textTransform: "none" }}>{message.subject || "(no subject)"}</h3>
          <button className="secondary" onClick={onClose}>
            Close
          </button>
        </div>

        <div className="email-modal-meta">
          <div>
            <span className="muted">From:</span> {message.from}
          </div>
          {message.to && (
            <div>
              <span className="muted">To:</span> {message.to}
            </div>
          )}
          <div>
            <span className="muted">Date:</span> {message.date ? new Date(message.date).toLocaleString() : "unknown"}
          </div>
          {message.category && (
            <div>
              <span className="category-pill">{message.category}</span>
            </div>
          )}
        </div>

        <div className="email-modal-actions">
          {message.unread ? (
            <button className="link-btn" onClick={() => onAction("mark_unread")}>
              Mark unread
            </button>
          ) : (
            <button className="link-btn" onClick={() => onAction("mark_read")}>
              Mark read
            </button>
          )}
          <button className="link-btn" onClick={() => onAction("star")}>
            Star
          </button>
          <button className="link-btn" onClick={() => onAction("archive")}>
            Archive
          </button>
          <button className="link-btn danger" onClick={() => onAction("trash")}>
            Trash
          </button>
        </div>

        <div className="email-modal-body">{message.body_text || "(no content)"}</div>
      </div>
    </div>
  );
}
