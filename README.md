# TeamBoards

A team task board with a **LangChain** assistant inside **Django**. The UI is Next.js; Django is the source of truth for accounts, permissions, and every write to Postgres.

The chatbot is not a Next.js feature. Next.js only streams tokens. LangChain runs on the server, next to the ORM, so the model can create, move, assign, and comment on cards **after** Django has checked membership.

Built on [Cookiecutter Django](https://github.com/cookiecutter/cookiecutter-django/) (Django 6, DRF, Docker Compose).

---

## Why LangChain lives in Django

| Layer | Role |
| --- | --- |
| **Gemini 2.5 Flash** | The model. It predicts text and tool calls. |
| **LangChain** | Glue: prompts, Pydantic schemas, `bind_tools`, streaming. |
| **Django** | Auth, membership, ORM writes, SSE. Tools are ordinary Python that hit Postgres. |
| **Next.js** | Thin client. `Authorization: Token …` and a fetch reader for SSE. |

The model never talks to Postgres. It asks to run `create_task`. Django decides whether that user may write that row.

If LangChain ran in the browser, the Google API key and every permission check would sit in the client. That is why the chain is a Django module: `djangoproject/boards/llm.py`.

---

## LangChain architecture

This is **not** a single LCEL string chain anymore, and it is **not** LangGraph.

```
POST /api/chat/  (authenticated)
        │
        ▼
  board snapshot stuffed into the system prompt
        │
        ▼
  ChatGoogleGenerativeAI.bind_tools([...])
        │
        ├── stream tokens  →  SSE event { type: "token" }
        ├── tool_calls     →  Django runs the function → SSE { type: "tool" }
        │                     result goes back as ToolMessage
        └── no more tools  →  SSE { type: "done", reply: BoardReply }
```

### 1. Tools

`djangoproject/boards/tools.py` wraps ORM functions with LangChain `@tool` and a Pydantic `args_schema`.

Gemini may call:

| Tool | What Django does |
| --- | --- |
| `list_tasks` | Live cards, optional status filter |
| `create_task` | Insert one `Task` |
| `create_tasks_from_notes` | Structured parse of a pasted list, then insert many |
| `update_task_status` | Move todo / doing / done |
| `assign_task` | Set assignee by member email |
| `set_due_date` | `YYYY-MM-DD` or clear |
| `set_priority` | low / medium / high / urgent |
| `add_comment` | Comment row + activity |
| `apply_label` | Attach an existing workspace label |

Every tool re-checks: the user is a member of the project’s workspace. Outsiders get a string error back to the model, not a 500.

A short loop (max 5 rounds) in `run_board_chat_stream` handles “create this, then tell me what’s todo.” That is agent-lite, not LangGraph.

### 2. Structured output

Free text is easy to misread. Pydantic schemas are the contract:

- Tool arguments (`TaskDraft`, `UpdateTaskStatusInput`, …) are sent to Gemini as function definitions.
- `create_tasks_from_notes` uses `llm.with_structured_output(ProposedTaskList)` so a messy paragraph becomes `{ title, status, priority }[]`.
- The last SSE event is `BoardReply`: `message`, `board_changed`, `actions`. The UI refreshes the kanban only when `board_changed` is true.

### 3. Streaming

`llm.stream()` yields chunks. Django forwards them as `text/event-stream`.

Two server details matter:

- **DRF content negotiation** must allow the stream (or omit a strict `Accept: text/event-stream` from the client). Otherwise you get `406 Could not satisfy the request Accept header` before the view runs.
- **ASGI + a sync generator** buffers the whole reply (`list(sync_iterator)`). The chat view yields an **async** iterator and pulls each LangChain event with `sync_to_async(next)` so tokens can flush.

Gemini 2.5 thinking is set to `thinking_budget: 0` so answer tokens start sooner. Tool rounds still have no text; the UI shows “Working…” / “Updating the board…” until the model speaks.

### 4. Context stuffing (not RAG)

When `project_id` is present and the user is a member, Django stuffs a snapshot into the system prompt:

```
Project: Website (id=3)
- #12 [todo] (high) Write tests @you@studio.com due 2026-09-04
```

There is no vector store. The board is small; stuffing is enough. Tools exist so the snapshot can go stale after a write and the model can still `list_tasks`.

---

## Request path

1. Browser is on `/projects/3`. Next.js sends `project_id: 3` plus recent `{ role, content }` history.
2. `ChatView` authenticates (DRF token), builds the snapshot, starts SSE.
3. LangChain streams. Tool calls run in Django, membership-checked.
4. Next.js `streamChat()` reads `data: {...}\n\n` and grows the assistant bubble.
5. On `done.board_changed`, the board reloads from `/api/tasks/`.

Chat without a project URL can talk, but tools refuse writes: “Open a project board you belong to first.”

---

## Product (Django domain)

Cookiecutter Django plus a `boards` app:

- **Workspace** — team, owner/member
- **Project** — one kanban board
- **Task** — status, priority, assignee, due date, labels
- **Comment** / **Activity** — notes and an audit feed
- **Label** — new workspaces get Bug, Feature, Chore

Default kanban columns are empty on purpose. They are statuses (`todo` / `doing` / `done`), not seeded cards.

Accounts: custom user (email). Sign up and login for the SPA are DRF token endpoints. Django templates/allauth still exist at `:8000` but the app you use is Next.js at `:3000`.

---

## Repo layout (LangChain-related)

```
djangoproject/boards/llm.py       # model, prompt, tool loop, stream
djangoproject/boards/tools.py     # Django-backed @tool functions
djangoproject/boards/schemas.py   # Pydantic structured output
djangoproject/boards/api/chat.py  # POST /api/chat/ → SSE
frontend/lib/api.ts               # streamChat() SSE parser
frontend/app/ui.tsx               # Chat panel
```

Swap vendors by changing `build_chat_model()` (`ChatGoogleGenerativeAI` → `ChatOpenAI`, same LCEL slot). Keep tools and schemas.

---

## Security (read this before you fork)

**Do not commit secrets.** This repo gitignores `.envs/` except `*.example` files.

| Keep local only | Why |
| --- | --- |
| `.envs/.local/.django` | `GOOGLE_API_KEY`, Flower password |
| `.envs/.local/.postgres` | DB password |
| `.envs/.production/*` | `DJANGO_SECRET_KEY` and production DB |
| `frontend/.env.local` | API URL (harmless) plus anything you add later |

Copy examples:

```bash
cp .envs/.local/.django.example .envs/.local/.django
cp .envs/.local/.postgres.example .envs/.local/.postgres
cp frontend/.env.example frontend/.env.local
```

Put a [Google AI Studio](https://aistudio.google.com/apikey) key in `GOOGLE_API_KEY`. Restart Django after changing it.

Other rules baked into the app:

- Chat and tools require a logged-in user (`IsAuthenticated`).
- Tools filter `workspace__members=user`. A valid token for team A cannot mutate team B.
- The Gemini key is read from Django settings on the server, never sent to Next.js.
- CORS is limited to `http://localhost:3000` in local settings.

If an API key ever landed in git history, revoke it in Google AI Studio and issue a new one.

---

## Run locally (Docker)

From this directory (the one with `docker-compose.local.yml`):

```bash
cp .envs/.local/.django.example .envs/.local/.django
cp .envs/.local/.postgres.example .envs/.local/.postgres
# edit .envs/.local/.django and set GOOGLE_API_KEY

docker compose -f docker-compose.local.yml up -d
```

API: `http://127.0.0.1:8000`  
Admin: `http://127.0.0.1:8000/admin/` (create a superuser inside the container if you need it)

```bash
docker compose -f docker-compose.local.yml exec django python manage.py createsuperuser
```

Frontend (on the host):

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

UI: `http://localhost:3000` — register, create a workspace, open a board, use the assistant.

On Windows, Docker volume mounts often **do not** trigger Uvicorn reload. After Python changes:

```bash
docker compose -f docker-compose.local.yml restart django
```

---

## Tests

```bash
docker compose -f docker-compose.local.yml exec django pytest djangoproject/boards/tests -q
```

Chat tests mock Gemini. Tool tests hit the ORM (create / move / membership deny). They do not need `GOOGLE_API_KEY`.

---

## Environment

| Variable | Where | Purpose |
| --- | --- | --- |
| `GOOGLE_API_KEY` | `.envs/.local/.django` | Gemini. Empty → chat returns a configuration error event. |
| `GEMINI_MODEL` | same | Default `gemini-2.5-flash`. |
| `NEXT_PUBLIC_API_URL` | `frontend/.env.local` | Default `http://127.0.0.1:8000`. |

---

## What this is not (yet)

- RAG / embeddings / a vector database (the board is stuffed into the prompt)
- LangGraph
- LangSmith tracing
- Server-side chat memory (history is resent from the browser, last 20 turns)

Those are the next LangChain layers if the board outgrows context stuffing.
