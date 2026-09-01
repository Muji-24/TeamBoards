"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react";

import { clearSession, errorMessage, getEmail, getToken, streamChat } from "@/lib/api";

type ChatTurn = { role: "human" | "ai" | "tool"; content: string };

function projectIdFromPath(pathname: string): number | undefined {
  const match = pathname.match(/^\/projects\/(\d+)/);
  return match ? Number(match[1]) : undefined;
}

export function Shell({
  children,
  onBoardChanged,
  board,
}: {
  children: ReactNode;
  onBoardChanged?: () => void;
  board?: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const projectId = projectIdFromPath(pathname);
  const [email, setEmail] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    setEmail(getEmail());
    setReady(true);
  }, [router]);

  if (!ready) {
    return <div className="app loading">Loading…</div>;
  }

  const initial = (email ?? "?").slice(0, 1).toUpperCase();

  return (
    <div className={`app${chatOpen ? " chat-open" : ""}`}>
      <aside className="rail">
        <Link href="/" className="mark" aria-label="Boards home">
          B
        </Link>
        <nav>
          <Link href="/" className={`nav${pathname === "/" ? " active" : ""}`} title="Workspaces">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path
                d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-5v-6H10v6H5a1 1 0 0 1-1-1v-9.5Z"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinejoin="round"
              />
            </svg>
          </Link>
        </nav>
        <div className="rail-foot" title={email ?? ""}>
          {initial}
        </div>
      </aside>
      <div className="stage">
        <header className="topbar">
          <Link href="/" className="brand">
            Boards
          </Link>
          <div className="row">
            <span className="muted">{email}</span>
            <button
              className="ghost small chat-fab"
              type="button"
              onClick={() => setChatOpen((open) => !open)}
            >
              {chatOpen ? "Close chat" : "Assistant"}
            </button>
            <button
              className="ghost small"
              type="button"
              onClick={() => {
                clearSession();
                router.replace("/login");
              }}
            >
              Sign out
            </button>
          </div>
        </header>
        <div className="stage-body">
          <div className={`stage-main${board ? " is-board" : ""}`}>{children}</div>
          <button
            className="chat-scrim"
            type="button"
            aria-label="Close assistant"
            onClick={() => setChatOpen(false)}
          />
          <ChatPanel
            projectId={projectId}
            onBoardChanged={onBoardChanged}
            onClose={() => setChatOpen(false)}
          />
        </div>
      </div>
    </div>
  );
}

export function AuthForm({
  title,
  submitLabel,
  extra,
  onSubmit,
}: {
  title: string;
  submitLabel: string;
  extra?: ReactNode;
  onSubmit: (email: string, password: string, name: string) => Promise<void>;
}) {
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setPending(true);
    const form = new FormData(event.currentTarget);
    try {
      await onSubmit(
        String(form.get("email") ?? ""),
        String(form.get("password") ?? ""),
        String(form.get("name") ?? ""),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
      setPending(false);
    }
  }

  return (
    <div className="auth-screen">
      <aside className="auth-hero">
        <Link href="/" className="mark" aria-label="Boards">
          B
        </Link>
        <div>
          <p className="eyebrow" style={{ color: "#9aa3b2" }}>
            Django API · Next.js
          </p>
          <h1>Plan work. Talk to the board.</h1>
        </div>
        <ul>
          <li>Workspaces and membership live in Django.</li>
          <li>Boards are three columns: to do, doing, done.</li>
          <li>The assistant can add and move cards.</li>
        </ul>
      </aside>
      <div className="auth-panel">
        <main className="auth card">
          <p className="eyebrow">Account</p>
          <h1>{title}</h1>
          <p className="muted">JSON to Django. The UI only holds your token.</p>
          <form className="stack" onSubmit={handleSubmit} style={{ marginTop: 16 }}>
            {extra}
            <label className="field">
              <span>Email</span>
              <input name="email" type="email" placeholder="you@studio.com" required />
            </label>
            <label className="field">
              <span>Password</span>
              <input
                name="password"
                type="password"
                placeholder="8+ characters"
                required
                minLength={8}
              />
            </label>
            {error ? <p className="error">{error}</p> : null}
            <button type="submit" disabled={pending}>
              {pending ? "Working…" : submitLabel}
            </button>
          </form>
        </main>
      </div>
    </div>
  );
}

export function ChatPanel({
  projectId,
  onBoardChanged,
  onClose,
}: {
  projectId?: number;
  onBoardChanged?: () => void;
  onClose?: () => void;
}) {
  const [turns, setTurns] = useState<ChatTurn[]>([
    {
      role: "ai",
      content:
        "I can list, add, and move cards on this board. Ask what’s todo, or say “add a card: write tests”.",
    },
  ]);
  const [text, setText] = useState("");
  const [pending, setPending] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [turns, pending]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const message = text.trim();
    if (!message) return;
    setText("");
    setError("");
    const history = turns
      .filter((turn) => turn.role === "human" || turn.role === "ai")
      .map((turn) => ({ role: turn.role as "human" | "ai", content: turn.content }));
    setTurns((prev) => [...prev, { role: "human", content: message }, { role: "ai", content: "" }]);
    setPending(true);
    setStatus("Working…");
    let boardChanged = false;
    try {
      await streamChat(
        {
          message,
          history,
          project_id: projectId ?? null,
        },
        (event) => {
          if (event.type === "status") {
            setStatus(event.text);
          } else if (event.type === "token") {
            setStatus("");
            setTurns((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last?.role === "ai") {
                next[next.length - 1] = { ...last, content: last.content + event.text };
              }
              return next;
            });
          } else if (event.type === "tool") {
            setTurns((prev) => {
              const next = [...prev];
              if (next[next.length - 1]?.role === "ai") {
                next.pop();
              }
              next.push({ role: "tool", content: event.result });
              next.push({ role: "ai", content: "" });
              return next;
            });
          } else if (event.type === "done") {
            boardChanged = event.reply.board_changed;
            setTurns((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last?.role === "ai" && !last.content.trim() && event.reply.message) {
                next[next.length - 1] = { ...last, content: event.reply.message };
              }
              return next;
            });
          } else if (event.type === "error") {
            setError(event.detail);
          }
        },
      );
      if (boardChanged) {
        onBoardChanged?.();
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPending(false);
      setStatus("");
    }
  }

  return (
    <aside className="chat">
      <header>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2>Assistant</h2>
          <button className="ghost small chat-fab" type="button" onClick={onClose}>
            Close
          </button>
        </div>
        <p>
          {projectId
            ? "Can list, add, and move cards on this board."
            : "Open a board to let me change tasks."}
        </p>
      </header>
      <div className="chat-log" ref={logRef}>
        {turns.map((turn, i) =>
          turn.role === "ai" && !turn.content && pending && i === turns.length - 1 ? (
            <div key={`${turn.role}-${i}`} className="bubble ai muted">
              {status || "Working…"}
            </div>
          ) : turn.role === "ai" && turn.content && pending && i === turns.length - 1 ? (
            <div key={`${turn.role}-${i}`} className="bubble ai streaming">
              {turn.content}
            </div>
          ) : turn.content ? (
            <div key={`${turn.role}-${i}`} className={`bubble ${turn.role}`}>
              {turn.content}
            </div>
          ) : null,
        )}
      </div>
      {error ? (
        <p className="error" style={{ padding: "0 12px 8px" }}>
          {error}
        </p>
      ) : null}
      <form onSubmit={onSubmit}>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={projectId ? "Add a card, or ask what’s done…" : "Ask about your boards…"}
        />
        <button type="submit" disabled={pending}>
          Send
        </button>
      </form>
    </aside>
  );
}
