import { FormEvent, useEffect, useState } from "react";
import { runAction } from "../api/actions";
import { ApiError, api } from "../api/client";
import type { Category, MessageSummary, ProposeResponse } from "../api/types";
import { ConfirmActionModal } from "./ConfirmActionModal";

const PAGE_SIZE = 50;

export function Search() {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [sender, setSender] = useState("");
  const [after, setAfter] = useState("");
  const [before, setBefore] = useState("");
  const [unreadOnly, setUnreadOnly] = useState(false);

  const [categories, setCategories] = useState<Category[]>([]);
  const [results, setResults] = useState<MessageSummary[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [pendingProposal, setPendingProposal] = useState<ProposeResponse | null>(null);
  const [confirmResolver, setConfirmResolver] = useState<((v: boolean) => void) | null>(null);
  const [actionBusy, setActionBusy] = useState(false);

  const browsing = !query.trim();

  useEffect(() => {
    api.categories().then(setCategories).catch(() => undefined);
    // Open the tab showing recent mail, like an inbox — not an empty screen
    // waiting for a query.
    fetchResults();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function fetchResults(e?: FormEvent) {
    e?.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const filters = {
        category: category || undefined,
        sender: sender || undefined,
        after: after || undefined,
        before: before || undefined,
        unread_only: unreadOnly,
      };
      let rows: MessageSummary[];
      if (browsing) {
        rows = await api.listMessages({ ...filters, limit: PAGE_SIZE, offset: 0 });
        setHasMore(rows.length === PAGE_SIZE);
      } else {
        rows = await api.search({ ...filters, q: query, limit: PAGE_SIZE });
        setHasMore(false); // relevance-ranked results aren't meaningfully paginated
      }
      setResults(rows);
      setSelected(new Set());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Search failed.");
    } finally {
      setLoading(false);
    }
  }

  async function loadMore() {
    setLoadingMore(true);
    setError(null);
    try {
      const rows = await api.listMessages({
        category: category || undefined,
        sender: sender || undefined,
        after: after || undefined,
        before: before || undefined,
        unread_only: unreadOnly,
        limit: PAGE_SIZE,
        offset: results?.length ?? 0,
      });
      setResults((prev) => [...(prev ?? []), ...rows]);
      setHasMore(rows.length === PAGE_SIZE);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load more.");
    } finally {
      setLoadingMore(false);
    }
  }

  function toggleSelected(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function confirmViaModal(proposal: ProposeResponse): Promise<boolean> {
    return new Promise((resolve) => {
      setPendingProposal(proposal);
      setConfirmResolver(() => resolve);
    });
  }

  function handleModalDecision(decision: boolean) {
    // Keep the modal open with a busy indicator until doAction's full
    // promise chain (confirm/cancel call + result refresh) settles below —
    // resolving here only unblocks runAction, it doesn't finish the work.
    setActionBusy(true);
    confirmResolver?.(decision);
  }

  async function doAction(action: "mark_read" | "mark_unread" | "star" | "unstar" | "archive" | "trash", ids: string[]) {
    setError(null);
    try {
      await runAction(
        { action, message_ids: ids },
        { alwaysConfirm: action === "archive" || action === "trash", confirm: confirmViaModal }
      );
      await fetchResults();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Action failed.");
    } finally {
      setPendingProposal(null);
      setConfirmResolver(null);
      setActionBusy(false);
    }
  }

  const selectedIds = Array.from(selected);

  return (
    <div className="search-view">
      <form className="search-filters" onSubmit={fetchResults}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search your inbox, or leave empty to browse recent mail..."
          className="search-query"
        />
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">All categories</option>
          {categories.map((c) => (
            <option key={c.name} value={c.name}>
              {c.name}
            </option>
          ))}
        </select>
        <input type="text" value={sender} onChange={(e) => setSender(e.target.value)} placeholder="From contains..." />
        <input type="date" value={after} onChange={(e) => setAfter(e.target.value)} title="After" />
        <input type="date" value={before} onChange={(e) => setBefore(e.target.value)} title="Before" />
        <label className="checkbox-label">
          <input type="checkbox" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} />
          Unread only
        </label>
        <button type="submit" disabled={loading}>
          {loading ? "Loading…" : browsing ? "Refresh" : "Search"}
        </button>
      </form>

      {error && <div className="error-banner">{error}</div>}

      {selectedIds.length > 0 && (
        <div className="bulk-toolbar">
          <span>{selectedIds.length} selected</span>
          <button onClick={() => doAction("mark_read", selectedIds)}>Mark read</button>
          <button onClick={() => doAction("archive", selectedIds)}>Archive</button>
          <button className="danger" onClick={() => doAction("trash", selectedIds)}>
            Trash
          </button>
        </div>
      )}

      {results && results.length === 0 && (
        <div className="empty-state">{browsing ? "No mail matches these filters." : "No matching emails."}</div>
      )}

      {results && results.length > 0 && (
        <>
          <table className="results-table">
            <thead>
              <tr>
                <th />
                <th>From</th>
                <th>Subject</th>
                <th>Date</th>
                <th>Category</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {results.map((m) => (
                <tr key={m.id} className={m.unread ? "unread" : ""}>
                  <td>
                    <input type="checkbox" checked={selected.has(m.id)} onChange={() => toggleSelected(m.id)} />
                  </td>
                  <td className="cell-from">{m.from}</td>
                  <td className="cell-subject" title={m.snippet}>
                    {m.subject}
                  </td>
                  <td className="cell-date muted">{m.date ? m.date.slice(0, 10) : ""}</td>
                  <td>{m.category && <span className="category-pill">{m.category}</span>}</td>
                  <td className="cell-actions">
                    {m.unread ? (
                      <button className="link-btn" onClick={() => doAction("mark_read", [m.id])}>
                        Mark read
                      </button>
                    ) : (
                      <button className="link-btn" onClick={() => doAction("mark_unread", [m.id])}>
                        Mark unread
                      </button>
                    )}
                    <button className="link-btn" onClick={() => doAction("star", [m.id])}>
                      Star
                    </button>
                    <button className="link-btn" onClick={() => doAction("archive", [m.id])}>
                      Archive
                    </button>
                    <button className="link-btn danger" onClick={() => doAction("trash", [m.id])}>
                      Trash
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {browsing && hasMore && (
            <div style={{ textAlign: "center", marginTop: 14 }}>
              <button className="secondary" onClick={loadMore} disabled={loadingMore}>
                {loadingMore ? "Loading…" : "Load more"}
              </button>
            </div>
          )}
        </>
      )}

      {pendingProposal && (
        <ConfirmActionModal
          proposal={pendingProposal}
          busy={actionBusy}
          onConfirm={() => handleModalDecision(true)}
          onCancel={() => handleModalDecision(false)}
        />
      )}
    </div>
  );
}
