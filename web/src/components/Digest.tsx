import { useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import type { DigestResponse } from "../api/types";
import { renderMarkdown } from "../util/markdown";

export function Digest() {
  const [digest, setDigest] = useState<DigestResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadLatest();
  }, []);

  async function loadLatest() {
    setLoading(true);
    setError(null);
    try {
      setDigest(await api.digestLatest());
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setDigest(null);
      } else {
        setError(e instanceof ApiError ? e.message : "Failed to load the digest.");
      }
    } finally {
      setLoading(false);
    }
  }

  async function generateNow() {
    setGenerating(true);
    setError(null);
    try {
      const result = await api.digestRun();
      setDigest(result.digest as DigestResponse);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to generate the digest.");
    } finally {
      setGenerating(false);
    }
  }

  const hasStructuredData = digest && digest.category_counts !== undefined;

  return (
    <div className="digest-view">
      <div className="digest-header">
        <div>
          <h2>Morning digest</h2>
          {digest && (
            <div className="muted">Generated {new Date(digest.generated_at).toLocaleString()}</div>
          )}
        </div>
        <button onClick={generateNow} disabled={generating}>
          {generating ? "Syncing, classifying, and summarizing…" : "Generate now"}
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {loading && <div className="empty-state">Loading…</div>}

      {!loading && !digest && !error && (
        <div className="empty-state">No digest yet — click "Generate now" to create one.</div>
      )}

      {digest && hasStructuredData && <StructuredDigest digest={digest} />}

      {digest && !hasStructuredData && (
        <div className="digest-content" dangerouslySetInnerHTML={{ __html: renderMarkdown(digest.content_markdown) }} />
      )}
    </div>
  );
}

const JOB_STATUS_LABELS: Record<string, string> = {
  interview: "Interview",
  moving_forward: "Moving forward",
  offer: "Offer",
};

function StructuredDigest({ digest }: { digest: DigestResponse }) {
  const unread = digest.unread_count;
  const categoryCounts = Object.entries(digest.category_counts ?? {}).sort((a, b) => b[1] - a[1]);
  const job = digest.job_highlights;
  const hasJobHighlights = job && (job.interview.length || job.moving_forward.length || job.offer.length || job.rejected_count);

  return (
    <div className="digest-structured">
      <div className="digest-stat-row">
        <div className="digest-stat-tile">
          <div className="digest-stat-number">{unread}</div>
          <div className="digest-stat-label">unread email{unread === 1 ? "" : "s"}</div>
        </div>
        <div className="digest-category-pills">
          {categoryCounts.map(([category, count]) => (
            <span className="category-pill" key={category}>
              {category} <strong>{count}</strong>
            </span>
          ))}
        </div>
      </div>

      {hasJobHighlights && (
        <section className="digest-section">
          <div className="digest-section-title">Job search pipeline</div>
          <div className="jobs-highlights-row">
            {(["interview", "moving_forward", "offer"] as const).map((status) =>
              (job?.[status] ?? []).map((a) => (
                <div className={`highlight-card status-${status.replace("_", "-")}`} key={a.id}>
                  <span className={`status-badge status-${status.replace("_", "-")}`}>{JOB_STATUS_LABELS[status]}</span>
                  <div className="highlight-card-company">{a.company}</div>
                  {a.role && <div className="highlight-card-role">{a.role}</div>}
                </div>
              ))
            )}
          </div>
          {!!job?.rejected_count && (
            <div className="muted" style={{ marginTop: 8 }}>
              {job.rejected_count} rejection{job.rejected_count === 1 ? "" : "s"} this week.
            </div>
          )}
        </section>
      )}

      {!!digest.interview_schedule?.length && (
        <section className="digest-section">
          <div className="digest-section-title">Interview / meeting schedule</div>
          <div className="jobs-highlights-row">
            {digest.interview_schedule.map((item, i) => (
              <div className="highlight-card status-interview" key={i}>
                <span className="status-badge status-interview">{item.when}</span>
                <div className="highlight-card-role" style={{ marginTop: 6 }}>
                  {item.summary}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {!!digest.action_items?.length && (
        <section className="digest-section">
          <div className="digest-section-title">Action items / needs a reply</div>
          <ul className="digest-checklist">
            {digest.action_items.map((item, i) => (
              <li key={i}>{item.summary}</li>
            ))}
          </ul>
        </section>
      )}

      {!!digest.category_summaries?.length && (
        <section className="digest-section">
          <div className="digest-section-title">Summaries</div>
          {digest.category_summaries.map((item, i) => (
            <div className="digest-summary-row" key={i}>
              <span className="category-pill">{item.category}</span>
              <span>{item.summary}</span>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}
