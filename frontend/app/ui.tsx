"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  clearSession,
  errorMessage,
  fetchChatHistory,
  getEmail,
  getToken,
  streamChat,
} from "@/lib/api";

type ToolStep = { name: string; label: string; result: string };
type ChatTurn =
  | { id: string; role: "human"; content: string }
  | { id: string; role: "ai"; content: string; tools: ToolStep[]; actions: string[] };

function newId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function ChatMarkdown({ text }: { text: string }) {
  return (
    <div className="md-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}

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
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [text, setText] = useState("");
  const [pending, setPending] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  const boxId = useId();

  useEffect(() => {
    let cancelled = false;
    setLoaded(false);
    fetchChatHistory(projectId ?? null)
      .then((data) => {
        if (cancelled) return;
        setTurns(
          data.messages
            .filter((item) => item.content.trim())
            .map((item) =>
              item.role === "human"
                ? { id: newId(), role: "human" as const, content: item.content }
                : {
                    id: newId(),
                    role: "ai" as const,
                    content: item.content,
                    tools: [],
                    actions: [],
                  },
            ),
        );
      })
      .catch(() => {
        if (!cancelled) setTurns([]);
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [turns, pending, status]);

  async function send(message: string) {
    const trimmed = message.trim();
    if (!trimmed || pending) return;
    setText("");
    setError("");
    const history = turns.map((turn) => ({
      role: turn.role,
      content: turn.content,
    }));
    const aiId = newId();
    setTurns((prev) => [
      ...prev,
      { id: newId(), role: "human", content: trimmed },
      { id: aiId, role: "ai", content: "", tools: [], actions: [] },
    ]);
    setPending(true);
    setStatus("Working…");
    let boardChanged = false;
    try {
      await streamChat(
        {
          message: trimmed,
          history,
          project_id: projectId ?? null,
        },
        (event) => {
          if (event.type === "status") {
            setStatus(event.text);
          } else if (event.type === "token") {
            setStatus("");
            setTurns((prev) =>
              prev.map((turn) =>
                turn.id === aiId && turn.role === "ai"
                  ? { ...turn, content: turn.content + event.text }
                  : turn,
              ),
            );
          } else if (event.type === "tool") {
            setStatus("");
            const step: ToolStep = {
              name: event.name,
              label: event.label || event.name.replaceAll("_", " "),
              result: event.result,
            };
            setTurns((prev) =>
              prev.map((turn) =>
                turn.id === aiId && turn.role === "ai"
                  ? { ...turn, tools: [...turn.tools, step] }
                  : turn,
              ),
            );
          } else if (event.type === "done") {
            boardChanged = event.reply.board_changed;
            setTurns((prev) =>
              prev.map((turn) => {
                if (turn.id !== aiId || turn.role !== "ai") return turn;
                return {
                  ...turn,
                  content: turn.content.trim() ? turn.content : event.reply.message,
                  actions: event.reply.actions,
                };
              }),
            );
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

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void send(text);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void send(text);
    }
  }

  const suggestions = projectId
    ? ["What's on this board?", "What should I work on next?", "Find overdue or unassigned cards"]
    : ["How do I use this assistant?"];
  const last = turns[turns.length - 1];
  const showStatus = pending && last?.role === "ai" && !last.content;

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
            ? "LangGraph agent · live board tools · markdown replies"
            : "Open a board so I can read and change cards."}
        </p>
      </header>
      <div className="chat-log" ref={logRef}>
        {loaded && turns.length === 0 ? (
          <div className="chat-welcome">
            <p className="eyebrow">LangChain</p>
            <h3>Ask the board, don’t guess.</h3>
            <p>
              I look up live cards with tools, then answer in structured markdown. Nothing is
              hardcoded into the prompt.
            </p>
            <div className="chat-suggestions">
              {suggestions.map((item) => (
                <button key={item} type="button" className="suggest" onClick={() => void send(item)}>
                  {item}
                </button>
              ))}
            </div>
          </div>
        ) : null}
        {turns.map((turn) =>
          turn.role === "human" ? (
            <div key={turn.id} className="bubble human">
              {turn.content}
            </div>
          ) : (
            <div
              key={turn.id}
              className={`ai-turn${pending && turn.id === last?.id ? " streaming" : ""}`}
            >
              {turn.tools.length ? (
                <ol className="tool-rail">
                  {turn.tools.map((step, index) => (
                    <li key={`${step.name}-${index}`} title={step.result}>
                      {step.label}
                    </li>
                  ))}
                </ol>
              ) : null}
              {turn.content ? <ChatMarkdown text={turn.content} /> : null}
              {turn.actions.length ? (
                <ul className="action-recap">
                  {turn.actions.map((action) => (
                    <li key={action}>{action}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ),
        )}
        {showStatus ? (
          <div className="ai-turn pending">
            <span className="dots" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
            <span>{status || "Working…"}</span>
          </div>
        ) : null}
      </div>
      {error ? (
        <p className="error" style={{ padding: "0 16px 8px" }}>
          {error}
        </p>
      ) : null}
      {loaded && turns.length > 0 && !pending ? (
        <div className="chat-suggestions bar">
          {suggestions.map((item) => (
            <button key={item} type="button" className="suggest" onClick={() => void send(item)}>
              {item}
            </button>
          ))}
        </div>
      ) : null}
      <form className="chat-composer" onSubmit={onSubmit}>
        <label className="sr-only" htmlFor={boxId}>
          Message
        </label>
        <textarea
          id={boxId}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          rows={2}
          placeholder={projectId ? "Ask, plan, or add cards…" : "Ask about Boards…"}
          disabled={pending}
        />
        <button type="submit" disabled={pending || !text.trim()}>
          Send
        </button>
      </form>
    </aside>
  );
}
