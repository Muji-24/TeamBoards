const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const TOKEN_KEY = "boards_token";
const EMAIL_KEY = "boards_email";

export type Membership = { id: number; user_id: number; email: string; role: "owner" | "member" };

export type Workspace = {
  id: number;
  name: string;
  created_at: string;
  members: Membership[];
  my_role: "owner" | "member";
  project_count: number;
  task_count: number;
};

export type Project = {
  id: number;
  workspace: number;
  name: string;
  created_at: string;
  open_count: number;
};

export type TaskStatus = "todo" | "doing" | "done";
export type Priority = "low" | "medium" | "high" | "urgent";

export type Label = {
  id: number;
  workspace: number;
  name: string;
  color: string;
};

export type Task = {
  id: number;
  project: number;
  title: string;
  description: string;
  status: TaskStatus;
  priority: Priority;
  assignee: number | null;
  assignee_email: string | null;
  created_by: number | null;
  created_by_email: string | null;
  due_date: string | null;
  labels: Label[];
  comment_count: number;
  created_at: string;
  updated_at: string;
};

export type Comment = {
  id: number;
  task: number;
  author: number | null;
  author_email: string | null;
  body: string;
  created_at: string;
};

export type Activity = {
  id: number;
  workspace: number;
  project: number | null;
  task: number | null;
  actor: number | null;
  actor_email: string | null;
  verb: string;
  summary: string;
  created_at: string;
};

export type Dashboard = {
  counts: {
    todo: number;
    doing: number;
    done: number;
    overdue: number;
    unassigned: number;
  };
  activity: Activity[];
};

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function getEmail(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(EMAIL_KEY);
}

export function setSession(token: string, email: string) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(EMAIL_KEY, email);
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(EMAIL_KEY);
}

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, body: unknown) {
    super(`API ${status}`);
    this.status = status;
    this.body = body;
  }
}

export type ChatStreamEvent =
  | { type: "token"; text: string }
  | { type: "tool"; name: string; result: string }
  | { type: "status"; text: string }
  | {
      type: "done";
      reply: { message: string; board_changed: boolean; actions: string[] };
    }
  | { type: "error"; detail: string };

export async function streamChat(
  body: {
    message: string;
    history: { role: "human" | "ai"; content: string }[];
    project_id: number | null;
  },
  onEvent: (event: ChatStreamEvent) => void,
): Promise<void> {
  const token = getToken();
  const response = await fetch(`${API_URL}/api/chat/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Token ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const text = await response.text();
    let data: unknown = text;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = { detail: text };
    }
    throw new ApiError(response.status, data);
  }

  if (!response.body) {
    throw new Error("Chat stream was empty.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split(/\r?\n\r?\n/);
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.split(/\r?\n/).find((entry) => entry.startsWith("data: "));
      if (!line) continue;
      onEvent(JSON.parse(line.slice(6)) as ChatStreamEvent);
    }
  }

  buffer += decoder.decode();
  if (buffer.trim()) {
    const line = buffer.split(/\r?\n/).find((entry) => entry.startsWith("data: "));
    if (line) {
      onEvent(JSON.parse(line.slice(6)) as ChatStreamEvent);
    }
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Token ${token}` } : {}),
    ...options.headers,
  };

  const response = await fetch(`${API_URL}${path}`, { ...options, headers });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;

  if (!response.ok) {
    throw new ApiError(response.status, data);
  }
  return data as T;
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError && err.body && typeof err.body === "object") {
    const body = err.body as Record<string, unknown>;
    const first = Object.values(body)[0];
    if (Array.isArray(first)) return String(first[0]);
    if (typeof first === "string") return first;
    if (typeof body.detail === "string") return body.detail;
  }
  if (err instanceof Error) return err.message;
  return "Something went wrong.";
}
