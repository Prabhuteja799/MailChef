import { FormEvent, useEffect, useRef, useState } from "react";
import { type ChatTurn, clearChatHistory, loadChatHistory, saveChatHistory } from "../api/chatHistory";
import { ApiError, api } from "../api/client";
import type { QuerySource } from "../api/types";
import { renderMarkdown } from "../util/markdown";

const SOURCES_PREVIEW_COUNT = 4;

export function Chat() {
  const [turns, setTurns] = useState<ChatTurn[]>(() => loadChatHistory());
  const [input, setInput] = useState("");
  const [asking, setAsking] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Persists across tab switches (component unmount/remount) and page
  // reloads — otherwise every switch back to this tab lost the conversation.
  useEffect(() => {
    saveChatHistory(turns);
  }, [turns]);

  // Without this, a long answer leaves the view scrolled near the top, with
  // the just-asked question bubble awkwardly cramped against the toolbar.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  function clearHistory() {
    setTurns([]);
    clearChatHistory();
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const question = input.trim();
    if (!question || asking) return;

    setInput("");
    setAsking(true);
    setTurns((prev) => [...prev, { question }]);

    try {
      const result = await api.query(question);
      setTurns((prev) =>
        prev.map((t, i) => (i === prev.length - 1 ? { ...t, answer: result.answer, sources: result.sources } : t))
      );
    } catch (e) {
      const message = e instanceof ApiError ? e.message : "Something went wrong.";
      setTurns((prev) => (prev.map((t, i) => (i === prev.length - 1 ? { ...t, error: message } : t))));
    } finally {
      setAsking(false);
    }
  }

  return (
    <div className="chat-view">
      {turns.length > 0 && (
        <div className="chat-toolbar">
          <button className="link-btn" onClick={clearHistory}>
            Clear conversation
          </button>
        </div>
      )}

      <div className="chat-log">
        {turns.length === 0 && (
          <div className="empty-state">
            Ask anything about your inbox — "Any interview schedules this week?", "Did the recruiter from Acme
            reply?", "Summarize everything from my landlord."
          </div>
        )}
        {turns.map((turn, i) => (
          <div className="chat-turn" key={i}>
            <div className="bubble bubble-user">{turn.question}</div>
            {turn.answer && (
              <div
                className="bubble bubble-assistant markdown-body"
                dangerouslySetInnerHTML={{ __html: renderMarkdown(turn.answer) }}
              />
            )}
            {turn.error && <div className="bubble bubble-error">{turn.error}</div>}
            {!turn.answer && !turn.error && <div className="bubble bubble-assistant thinking">Thinking…</div>}
            {turn.sources && turn.sources.length > 0 && <Sources sources={turn.sources} />}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <form className="chat-input-row" onSubmit={handleSubmit}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about your inbox..."
          disabled={asking}
        />
        <button type="submit" disabled={asking || !input.trim()}>
          Ask
        </button>
      </form>
    </div>
  );
}

function Sources({ sources }: { sources: QuerySource[] }) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? sources : sources.slice(0, SOURCES_PREVIEW_COUNT);
  const remaining = sources.length - visible.length;

  return (
    <div className="sources">
      {visible.map((s) => (
        <div className="source-chip" key={s.id} title={s.subject}>
          <span className="source-from">{s.from}</span>
          <span className="source-subject">{s.subject}</span>
        </div>
      ))}
      {remaining > 0 && (
        <button className="link-btn" onClick={() => setExpanded(true)}>
          +{remaining} more
        </button>
      )}
    </div>
  );
}
