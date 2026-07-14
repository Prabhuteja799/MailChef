import { useState } from "react";
import { Chat } from "./components/Chat";
import { Digest } from "./components/Digest";
import { Login } from "./components/Login";
import { Search } from "./components/Search";
import { clearConfig, loadConfig } from "./api/config";

type Tab = "chat" | "digest" | "search";

export default function App() {
  const [connected, setConnected] = useState(() => loadConfig() !== null);
  const [tab, setTab] = useState<Tab>("chat");

  if (!connected) {
    return <Login onConnected={() => setConnected(true)} />;
  }

  function disconnect() {
    clearConfig();
    setConnected(false);
  }

  return (
    <div className="app-shell">
      <nav className="sidebar">
        <div className="brand">MailChef</div>
        <button className={tab === "chat" ? "nav-item active" : "nav-item"} onClick={() => setTab("chat")}>
          Ask
        </button>
        <button className={tab === "digest" ? "nav-item active" : "nav-item"} onClick={() => setTab("digest")}>
          Digest
        </button>
        <button className={tab === "search" ? "nav-item active" : "nav-item"} onClick={() => setTab("search")}>
          Search &amp; Inbox
        </button>
        <div className="sidebar-spacer" />
        <button className="nav-item disconnect" onClick={disconnect}>
          Disconnect
        </button>
      </nav>
      <main className="content">
        {tab === "chat" && <Chat />}
        {tab === "digest" && <Digest />}
        {tab === "search" && <Search />}
      </main>
    </div>
  );
}
