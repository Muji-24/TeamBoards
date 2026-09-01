# TeamBoards

A team task board with a **LangChain / LangGraph** assistant inside **Django**. The UI is Next.js; Django is the source of truth for accounts, permissions, and every write to Postgres.

The chatbot is not a Next.js feature. Next.js streams tokens and renders **markdown**. LangGraph runs on the server, next to the ORM, so the model can create, move, assign, and comment on cards **after** Django has checked membership.

Built on [Cookiecutter Django](https://github.com/cookiecutter/cookiecutter-django/) (Django 6, Python 3.14, DRF, Docker Compose).

---

## Why LangChain lives in Django

| Layer | Role |
| --- | --- |
| **Gemini 2.5 Flash** | The model. It predicts text and tool calls. |
| **LangChain + LangGraph** | Glue: prompts, Pydantic schemas, ReAct agent graph, streaming. |
| **Django** | Auth, membership, ORM writes, SSE. Tools are ordinary Python that hit Postgres. |
| **Next.js** | Thin client. `Authorization: Token …` and a fetch reader for SSE. |

The model never talks to Postgres. It asks to run `create_task`. Django decides whether that user may write that row.

If LangChain ran in the browser, the Google API key and every permission check would sit in the client. That is why the chain is a Django module: `djangoproject/boards/llm.py`.

---

## LangChain architecture

The assistant is a **LangGraph agent** (`langchain.agents.create_agent`). Gemini chooses tools from their schemas. Django executes them. There is no stuffed task list and no fixed `for _ in range(5)` loop.

```
POST /api/chat/  (authenticated)
        │
        ▼
  ChatThread in Postgres (last 24 human/AI turns)
        │
        ▼
  LangGraph create_agent
  prompt = identity of the open board only
        │
        ├── stream tokens      →  SSE { type: "token" }
        ├── tool node (ORM)    →  SSE { type: "tool", label, result }
        └── graph completes    →  SSE { type: "done", reply: BoardReply }
```

### 1. Tools (live data, not a hardcoded dump)

`djangoproject/boards/tools.py` wraps ORM functions with LangChain `@tool` and a Pydantic `args_schema`. The model **reads** the board by calling tools.

| Tool | What Django does |
| --- | --- |
| `get_board_summary` | Counts, overdue, unassigned, recent activity |
| `search_tasks` | Title/description search with optional filters |
| `list_tasks` | Live cards, optional column |
| `get_task` | One card plus recent comments |
| `list_members` | Workspace emails/roles (for assign) |
| `plan_work` | Nested `with_structured_output(WorkPlan)`, optional create |
| `create_task` | Insert one `Task` |
| `create_tasks_from_notes` | Structured parse of a pasted list, then insert many |
| `update_task_status` | Move todo / doing / done |
| `assign_task` | Set assignee by member email |
| `set_due_date` | `YYYY-MM-DD` or clear |
| `set_priority` | low / medium / high / urgent |
| `add_comment` | Comment row + activity |
| `apply_label` | Attach an existing workspace label |

Every tool re-checks: the user is a member of the project’s workspace. Outsiders get a string error back to the model, not a 500.

LangGraph keeps calling tools until the model answers. Recursion is capped at 15 as a safety rail.

### 2. Structured output (nested chains)

Free text is easy to misread. Pydantic schemas are the contract:

- Tool arguments (`TaskDraft`, `SearchTasksInput`, …) are sent to Gemini as function definitions.
- `create_tasks_from_notes` uses `llm.with_structured_output(ProposedTaskList)`.
- `plan_work` calls a **second** chain `draft_work_plan()` → `WorkPlan`, then optionally writes cards.
- The last SSE event is `BoardReply`: `message`, `board_changed`, `actions`. The UI refreshes the kanban only when `board_changed` is true.

### 3. Streaming and markdown

LangGraph `stream_mode=["messages", "updates"]` yields tokens and tool results. Django forwards them as `text/event-stream`.

The model is instructed to reply in GitHub-flavored markdown. Next.js renders that with `react-markdown` (headings, lists, tables, code). Tool calls show as compact labels (“Reading the board”), not raw JSON blobs.

Two server details matter:

- **DRF content negotiation** must allow the stream (or omit a strict `Accept: text/event-stream` from the client). Otherwise you get `406` before the view runs.
- **ASGI + a sync generator** buffers the whole reply (`list(sync_iterator)`). The chat view yields an **async** iterator and pulls each event with `sync_to_async(next)` so tokens can flush.

Gemini 2.5 thinking is set to `thinking_budget: 0` so answer tokens start sooner.

### 4. Memory (not browser-only)

Turns are stored as `ChatThread` / `ChatMessage` (one thread per user+board). `GET /api/chat/?project_id=` reloads them. The system prompt only names the open project; the agent fetches live cards with tools. There is still no vector store / RAG — search is ORM `icontains`.

---

## Request path

1. Browser is on `/projects/3`. Next.js loads saved turns, then sends `project_id: 3` plus the new message.
2. `ChatView` authenticates (DRF token), loads the thread, starts SSE.
3. LangGraph streams. Tool calls run in Django, membership-checked.
4. Next.js `streamChat()` grows the markdown reply and shows tool chips.
5. On `done.board_changed`, the board reloads from `/api/tasks/`.

Chat without a project URL can talk, but tools refuse writes: “Open a project board you belong to first.”

### How replies look

The panel is a studio chat, not a dump of JSON:

- Assistant turns are GitHub-flavored **markdown** (headings, bullets, tables, `` `#12` ``).
- Tool calls appear as chips (“Reading the board”, “Creating a card”), not raw ORM strings.
- After writes, a short recap lists what actually changed; the kanban refreshes when `board_changed` is true.
- History survives refresh (`GET /api/chat/?project_id=`).

Try: *What’s on this board?* · *What should I work on next?* · *Find overdue or unassigned cards* · *Plan a launch and add the cards*.

---

## Product (Django domain)

Cookiecutter Django plus a `boards` app:

- **Workspace** — team, owner/member
- **Project** — one kanban board
- **Task** — status, priority, assignee, due date, labels
- **Comment** / **Activity** — notes and an audit feed
- **Label** — new workspaces get Bug, Feature, Chore
- **ChatThread** — persisted LangGraph conversation per user and board

Default kanban columns are empty on purpose. They are statuses (`todo` / `doing` / `done`), not seeded cards.

Accounts: custom user (email). Sign up and login for the SPA are DRF token endpoints. Django templates/allauth still exist at `:8000` but the app you use is Next.js at `:3000`.

---

## Repo layout (LangChain-related)

```
djangoproject/boards/llm.py       # LangGraph agent, nested structured chains, stream
djangoproject/boards/tools.py     # Django-backed @tool functions
djangoproject/boards/schemas.py   # Pydantic structured output
djangoproject/boards/api/chat.py  # POST /api/chat/ SSE + GET history
djangoproject/boards/models.py    # ChatThread / ChatMessage memory
frontend/lib/api.ts               # streamChat() SSE parser
frontend/app/ui.tsx               # Markdown chat panel
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
docker compose -f docker-compose.local.yml exec django python manage.py migrate
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

After pulling new Python deps (`langchain`, `langgraph`), sync the container venv (this project mounts a named volume over `.venv`):

```bash
docker compose -f docker-compose.local.yml exec django uv sync
docker compose -f docker-compose.local.yml restart django
```

On Windows, bind mounts often do not trigger Uvicorn reload. Restart `django` after Python edits even if `uv sync` was not needed.

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

- RAG / embeddings / a vector database (search is ORM, not vectors)
- LangSmith tracing

The next LangChain layer is RAG if a board is too large for `search_tasks`.
