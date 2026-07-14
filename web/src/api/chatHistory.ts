import type { QuerySource } from "./types";

export interface ChatTurn {
  question: string;
  answer?: string;
  sources?: QuerySource[];
  error?: string;
}

const STORAGE_KEY = "mailchef_chat_history";
// Bounds localStorage growth — old turns roll off rather than accumulating forever.
const MAX_TURNS = 50;

export function loadChatHistory(): ChatTurn[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as ChatTurn[]) : [];
  } catch {
    return [];
  }
}

export function saveChatHistory(turns: ChatTurn[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(turns.slice(-MAX_TURNS)));
}

export function clearChatHistory(): void {
  localStorage.removeItem(STORAGE_KEY);
}
