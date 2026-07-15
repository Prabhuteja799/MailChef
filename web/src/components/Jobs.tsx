import { useEffect, useMemo, useState } from "react";
import { ApiError, api } from "../api/client";
import type { JobApplication, JobApplicationDetail, JobStatus } from "../api/types";

const STATUS_ORDER: JobStatus[] = ["interview", "moving_forward", "offer", "applied", "acknowledged", "rejected", "other"];

// Anything at this tier is why the tracker exists — always shown up top,
// regardless of how noisy the rest of the pipeline gets.
const HIGHLIGHT_STATUSES: JobStatus[] = ["interview", "moving_forward", "offer"];

const STATUS_LABELS: Record<JobStatus, string> = {
  applied: "Applied",
  acknowledged: "Acknowledged",
  interview: "Interview",
  moving_forward: "Moving forward",
  offer: "Offer",
  rejected: "Rejected",
  other: "Other",
};

const STATUS_CLASS: Record<JobStatus, string> = {
  applied: "status-neutral",
  acknowledged: "status-neutral",
  interview: "status-interview",
  moving_forward: "status-moving-forward",
  offer: "status-offer",
  rejected: "status-rejected",
  other: "status-neutral",
};

export function Jobs() {
  const [applications, setApplications] = useState<JobApplication[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<JobApplicationDetail | null>(null);
  const [statusFilter, setStatusFilter] = useState<JobStatus | "all">("all");
  const [companyFilter, setCompanyFilter] = useState("");

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

  const counts = useMemo(() => {
    const c: Partial<Record<JobStatus, number>> = {};
    for (const a of applications ?? []) c[a.status] = (c[a.status] ?? 0) + 1;
    return c;
  }, [applications]);

  const highlights = useMemo(
    () => (applications ?? []).filter((a) => HIGHLIGHT_STATUSES.includes(a.status)),
    [applications]
  );

  const filtered = useMemo(() => {
    let rows = applications ?? [];
    if (statusFilter !== "all") rows = rows.filter((a) => a.status === statusFilter);
    if (companyFilter.trim()) {
      const needle = companyFilter.trim().toLowerCase();
      rows = rows.filter((a) => a.company.toLowerCase().includes(needle) || a.role?.toLowerCase().includes(needle));
    }
    return rows;
  }, [applications, statusFilter, companyFilter]);

  const total = applications?.length ?? 0;

  return (
    <div className="jobs-view">
      <div className="jobs-header">
        <div>
          <h2>Job search pipeline</h2>
          {!loading && applications && <div className="muted">{total} application(s) tracked</div>}
        </div>
        <button onClick={scanForUpdates} disabled={scanning}>
          {scanning ? "Scanning…" : "Scan for updates"}
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {scanning && (
        <div className="generating-banner">
          <span className="spinner" />
          Scanning mail for interview invites, replies, and rejections — this can take a few
          minutes for a lot of mail.
        </div>
      )}

      {loading && <div className="empty-state">Loading…</div>}

      {!loading && applications && applications.length === 0 && (
        <div className="empty-state">
          No tracked applications yet — click "Scan for updates" to extract interview invites, replies, and
          rejections from your inbox.
        </div>
      )}

      {!loading && applications && applications.length > 0 && (
        <>
          {highlights.length > 0 ? (
            <div className="jobs-highlights">
              <div className="jobs-highlights-label">Needs your attention</div>
              <div className="jobs-highlights-row">
                {highlights.map((a) => (
                  <button className={`highlight-card ${STATUS_CLASS[a.status]}`} key={a.id} onClick={() => openDetail(a.id)}>
                    <span className={`status-badge ${STATUS_CLASS[a.status]}`}>{STATUS_LABELS[a.status]}</span>
                    <div className="highlight-card-company">{a.company}</div>
                    {a.role && <div className="highlight-card-role">{a.role}</div>}
                    <div className="highlight-card-date muted">{a.status_updated_at.slice(0, 10)}</div>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="empty-state" style={{ padding: "16px 0" }}>
              No interviews, offers, or "moving forward" replies yet — they'll show up here first.
            </div>
          )}

          <div className="jobs-toolbar">
            <div className="jobs-chips">
              <button className={statusFilter === "all" ? "chip active" : "chip"} onClick={() => setStatusFilter("all")}>
                All ({total})
              </button>
              {STATUS_ORDER.filter((s) => counts[s]).map((status) => (
                <button
                  key={status}
                  className={statusFilter === status ? "chip active" : "chip"}
                  onClick={() => setStatusFilter(status)}
                >
                  {STATUS_LABELS[status]} ({counts[status]})
                </button>
              ))}
            </div>
            <input
              type="text"
              placeholder="Filter by company or role..."
              value={companyFilter}
              onChange={(e) => setCompanyFilter(e.target.value)}
              className="jobs-search-input"
            />
          </div>

          {filtered.length === 0 ? (
            <div className="empty-state">No applications match this filter.</div>
          ) : (
            <table className="jobs-table">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((a) => (
                  <tr key={a.id} onClick={() => openDetail(a.id)}>
                    <td className="cell-company">{a.company}</td>
                    <td className="muted cell-role">{a.role || "—"}</td>
                    <td>
                      <span className={`status-badge ${STATUS_CLASS[a.status]}`}>{STATUS_LABELS[a.status]}</span>
                    </td>
                    <td className="muted">{a.status_updated_at.slice(0, 10)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}

      {selected && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={() => setSelected(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3 style={{ textTransform: "none" }}>
              {selected.company}
              {selected.role ? ` — ${selected.role}` : ""}
            </h3>
            <div className="muted" style={{ marginBottom: 12 }}>
              <span className={`status-badge ${STATUS_CLASS[selected.status]}`}>{STATUS_LABELS[selected.status]}</span>
              {" · updated " + selected.status_updated_at.slice(0, 10)}
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
