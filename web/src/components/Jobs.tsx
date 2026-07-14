import { useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import type { JobApplication, JobApplicationDetail, JobStatus } from "../api/types";

const STATUS_ORDER: JobStatus[] = ["interview", "moving_forward", "offer", "applied", "acknowledged", "rejected", "other"];

const STATUS_LABELS: Record<JobStatus, string> = {
  applied: "Applied",
  acknowledged: "Acknowledged",
  interview: "Interview",
  moving_forward: "Moving forward",
  offer: "Offer",
  rejected: "Rejected",
  other: "Other",
};

export function Jobs() {
  const [applications, setApplications] = useState<JobApplication[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<JobApplicationDetail | null>(null);

  useEffect(() => {
    loadApplications();
  }, []);

  async function loadApplications() {
    setLoading(true);
    setError(null);
    try {
      setApplications(await api.jobsList());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load applications.");
    } finally {
      setLoading(false);
    }
  }

  async function scanForUpdates() {
    setScanning(true);
    setError(null);
    try {
      await api.jobsExtract();
      await loadApplications();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to scan for updates.");
    } finally {
      setScanning(false);
    }
  }

  async function openDetail(id: string) {
    setError(null);
    try {
      setSelected(await api.jobsDetail(id));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load application detail.");
    }
  }

  const grouped: Partial<Record<JobStatus, JobApplication[]>> = {};
  for (const a of applications ?? []) {
    (grouped[a.status] ??= []).push(a);
  }

  return (
    <div className="jobs-view">
      <div className="jobs-header">
        <h2>Job search pipeline</h2>
        <button onClick={scanForUpdates} disabled={scanning}>
          {scanning ? "Scanning your inbox…" : "Scan for updates"}
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {loading && <div className="empty-state">Loading…</div>}

      {!loading && applications && applications.length === 0 && (
        <div className="empty-state">
          No tracked applications yet — click "Scan for updates" to extract interview invites, replies, and
          rejections from your inbox.
        </div>
      )}

      {!loading && applications && applications.length > 0 && (
        <div className="jobs-board">
          {STATUS_ORDER.filter((status) => grouped[status]?.length).map((status) => (
            <div className="jobs-column" key={status}>
              <div className="jobs-column-header">
                {STATUS_LABELS[status]} <span className="muted">({grouped[status]!.length})</span>
              </div>
              {grouped[status]!.map((a) => (
                <button className="job-card" key={a.id} onClick={() => openDetail(a.id)}>
                  <div className="job-card-company">{a.company}</div>
                  {a.role && <div className="job-card-role">{a.role}</div>}
                  <div className="job-card-date muted">{a.status_updated_at.slice(0, 10)}</div>
                </button>
              ))}
            </div>
          ))}
        </div>
      )}

      {selected && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={() => setSelected(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3 style={{ textTransform: "none" }}>
              {selected.company}
              {selected.role ? ` — ${selected.role}` : ""}
            </h3>
            <div className="muted" style={{ marginBottom: 12 }}>
              Status: {STATUS_LABELS[selected.status]} (updated {selected.status_updated_at.slice(0, 10)})
            </div>
            <div className="modal-list">
              {selected.events.map((e) => (
                <div className="modal-list-row" key={e.id}>
                  <div className="modal-list-from">
                    {e.event_date.slice(0, 10)} · {STATUS_LABELS[e.event_type]}
                  </div>
                  <div className="modal-list-subject">{e.summary}</div>
                  {e.source_message && (
                    <div className="modal-list-date muted">
                      {e.source_message.from} — {e.source_message.subject}
                    </div>
                  )}
                </div>
              ))}
            </div>
            <div className="modal-actions">
              <button className="secondary" onClick={() => setSelected(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
