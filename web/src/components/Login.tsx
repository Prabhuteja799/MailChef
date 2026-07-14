import { FormEvent, useState } from "react";
import { ApiError, api } from "../api/client";
import { saveConfig } from "../api/config";

export function Login({ onConnected }: { onConnected: () => void }) {
  const [backendUrl, setBackendUrl] = useState("http://localhost:8080");
  const [apiToken, setApiToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setChecking(true);
    saveConfig({ backendUrl, apiToken });
    try {
      await api.health();
      onConnected();
    } catch (e) {
      const message = e instanceof ApiError ? e.message : "Could not reach that backend URL.";
      setError(message);
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={handleSubmit}>
        <h1>MailChef</h1>
        <p className="muted">Connect to your MailChef backend to get started.</p>

        <label>
          Backend URL
          <input
            type="text"
            value={backendUrl}
            onChange={(e) => setBackendUrl(e.target.value)}
            placeholder="https://your-app.fly.dev"
            required
          />
        </label>

        <label>
          API token
          <input
            type="password"
            value={apiToken}
            onChange={(e) => setApiToken(e.target.value)}
            placeholder="MAILCHEF_API_TOKEN"
            required
          />
        </label>

        {error && <div className="error-banner">{error}</div>}

        <button type="submit" disabled={checking}>
          {checking ? "Connecting..." : "Connect"}
        </button>
      </form>
    </div>
  );
}
