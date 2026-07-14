const BACKEND_URL_KEY = "mailchef_backend_url";
const API_TOKEN_KEY = "mailchef_api_token";

export interface StoredConfig {
  backendUrl: string;
  apiToken: string;
}

export function loadConfig(): StoredConfig | null {
  const backendUrl = localStorage.getItem(BACKEND_URL_KEY);
  const apiToken = localStorage.getItem(API_TOKEN_KEY);
  if (!backendUrl || !apiToken) return null;
  return { backendUrl, apiToken };
}

export function saveConfig(config: StoredConfig): void {
  localStorage.setItem(BACKEND_URL_KEY, config.backendUrl.replace(/\/+$/, ""));
  localStorage.setItem(API_TOKEN_KEY, config.apiToken);
}

export function clearConfig(): void {
  localStorage.removeItem(BACKEND_URL_KEY);
  localStorage.removeItem(API_TOKEN_KEY);
}
