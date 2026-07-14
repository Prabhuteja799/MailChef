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
      setDigest(result.digest);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to generate the digest.");
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="digest-view">
      <div className="digest-header">
        <h2>Morning digest</h2>
        <button onClick={generateNow} disabled={generating}>
          {generating ? "Syncing, classifying, and summarizing…" : "Generate now"}
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {loading && <div className="empty-state">Loading…</div>}

      {!loading && !digest && !error && (
        <div className="empty-state">No digest yet — click "Generate now" to create one.</div>
      )}

      {digest && (
        <>
          <div className="digest-meta muted">Generated {new Date(digest.generated_at).toLocaleString()}</div>
          <div className="digest-content" dangerouslySetInnerHTML={{ __html: renderMarkdown(digest.content_markdown) }} />
        </>
      )}
    </div>
  );
}
