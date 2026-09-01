"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, useEffect, useMemo, useState } from "react";

import {
  type Comment,
  type Label,
  type Membership,
  type Priority,
  type Project,
  type Task,
  type TaskStatus,
  type Workspace,
  api,
  errorMessage,
} from "@/lib/api";
import { Shell } from "../../ui";

const COLUMNS: { key: TaskStatus; label: string }[] = [
  { key: "todo", label: "To do" },
  { key: "doing", label: "Doing" },
  { key: "done", label: "Done" },
];

const PRIORITIES: Priority[] = ["low", "medium", "high", "urgent"];

export default function ProjectBoardPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [project, setProject] = useState<Project | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [labels, setLabels] = useState<Label[]>([]);
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [assigneeFilter, setAssigneeFilter] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("");
  const [labelFilter, setLabelFilter] = useState("");
  const [view, setView] = useState<"board" | "list">("board");
  const [openId, setOpenId] = useState<number | null>(null);

  async function load() {
    try {
      const proj = await api<Project>(`/api/projects/${id}/`);
      const [list, ws, labs] = await Promise.all([
        api<Task[]>(`/api/tasks/?project=${id}`),
        api<Workspace>(`/api/workspaces/${proj.workspace}/`),
        api<Label[]>(`/api/labels/?workspace=${proj.workspace}`),
      ]);
      setProject(proj);
      setTasks(list);
      setWorkspace(ws);
      setLabels(labs);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  useEffect(() => {
    void load();
  }, [id]);

  const visible = useMemo(() => {
    return tasks.filter((task) => {
      if (query && !`${task.title} ${task.description}`.toLowerCase().includes(query.toLowerCase())) {
        return false;
      }
      if (assigneeFilter === "none" && task.assignee) return false;
      if (assigneeFilter && assigneeFilter !== "none" && String(task.assignee) !== assigneeFilter) {
        return false;
      }
      if (priorityFilter && task.priority !== priorityFilter) return false;
      if (labelFilter && !task.labels.some((lab) => String(lab.id) === labelFilter)) return false;
      return true;
    });
  }, [tasks, query, assigneeFilter, priorityFilter, labelFilter]);

  const openTask = tasks.find((task) => task.id === openId) ?? null;

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      await api("/api/tasks/", {
        method: "POST",
        body: JSON.stringify({ project: Number(id), title }),
      });
      setTitle("");
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function patchTask(task: Task, body: Record<string, unknown>) {
    setError("");
    try {
      await api(`/api/tasks/${task.id}/`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Shell onBoardChanged={load} board>
      <p className="crumb">
        <Link href="/">Workspaces</Link>
        {project ? (
          <>
            {" / "}
            <Link href={`/workspaces/${project.workspace}`}>Workspace</Link>
            {` / ${project.name}`}
          </>
        ) : null}
      </p>
      <div className="page-head">
        <div>
          <h1>{project?.name ?? "Board"}</h1>
          <p className="lede muted">Filter, switch to a list, or open a card for people, dates, and comments.</p>
        </div>
        <form className="row" onSubmit={onCreate}>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Add a task"
            required
          />
          <button type="submit">Add</button>
        </form>
      </div>
      <div className="filters">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search title or description"
        />
        <select value={assigneeFilter} onChange={(e) => setAssigneeFilter(e.target.value)}>
          <option value="">Anyone</option>
          <option value="none">Unassigned</option>
          {(workspace?.members ?? []).map((member) => (
            <option key={member.user_id} value={member.user_id}>
              {member.email}
            </option>
          ))}
        </select>
        <select value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value)}>
          <option value="">Any priority</option>
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <select value={labelFilter} onChange={(e) => setLabelFilter(e.target.value)}>
          <option value="">Any label</option>
          {labels.map((lab) => (
            <option key={lab.id} value={lab.id}>
              {lab.name}
            </option>
          ))}
        </select>
        <div className="row">
          <button type="button" className={view === "board" ? "" : "ghost"} onClick={() => setView("board")}>
            Board
          </button>
          <button type="button" className={view === "list" ? "" : "ghost"} onClick={() => setView("list")}>
            List
          </button>
        </div>
      </div>
      {error ? <p className="error">{error}</p> : null}
      {view === "board" ? (
        <div className="board">
          {COLUMNS.map((col) => {
            const items = visible.filter((t) => t.status === col.key);
            return (
              <section key={col.key} className={`column ${col.key}`}>
                <header>
                  <h3>{col.label}</h3>
                  <span className="count">{items.length}</span>
                </header>
                <div className="column-body">
                  {items.map((task) => (
                    <article key={task.id} className="task" onClick={() => setOpenId(task.id)}>
                      <p>{task.title}</p>
                      <div className="task-meta">
                        <span className={`prio ${task.priority}`}>{task.priority}</span>
                        {task.assignee_email ? (
                          <span className="muted">{task.assignee_email.split("@")[0]}</span>
                        ) : null}
                        {task.due_date ? <span className="muted">{task.due_date}</span> : null}
                        {task.comment_count ? <span className="muted">{task.comment_count} notes</span> : null}
                      </div>
                      <div className="row" onClick={(event) => event.stopPropagation()}>
                        {COLUMNS.filter((c) => c.key !== task.status).map((c) => (
                          <button
                            key={c.key}
                            type="button"
                            className="ghost small"
                            onClick={() => void patchTask(task, { status: c.key })}
                          >
                            {c.label}
                          </button>
                        ))}
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      ) : (
        <div className="table-wrap">
          <table className="task-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Title</th>
                <th>Status</th>
                <th>Priority</th>
                <th>Assignee</th>
                <th>Due</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((task) => (
                <tr key={task.id} onClick={() => setOpenId(task.id)}>
                  <td>#{task.id}</td>
                  <td>{task.title}</td>
                  <td>{task.status}</td>
                  <td>{task.priority}</td>
                  <td>{task.assignee_email ?? "—"}</td>
                  <td>{task.due_date ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {openTask ? (
        <TaskDrawer
          task={openTask}
          members={workspace?.members ?? []}
          labels={labels}
          onClose={() => setOpenId(null)}
          onPatch={(body) => void patchTask(openTask, body)}
          onReload={load}
        />
      ) : null}
    </Shell>
  );
}

function TaskDrawer({
  task,
  members,
  labels,
  onClose,
  onPatch,
  onReload,
}: {
  task: Task;
  members: Membership[];
  labels: Label[];
  onClose: () => void;
  onPatch: (body: Record<string, unknown>) => void;
  onReload: () => Promise<void>;
}) {
  const [comments, setComments] = useState<Comment[]>([]);
  const [body, setBody] = useState("");
  const [description, setDescription] = useState(task.description);

  useEffect(() => {
    setDescription(task.description);
    void api<Comment[]>(`/api/tasks/${task.id}/comments/`).then(setComments).catch(() => setComments([]));
  }, [task.id, task.description]);

  async function onComment(event: FormEvent) {
    event.preventDefault();
    await api(`/api/tasks/${task.id}/comments/`, {
      method: "POST",
      body: JSON.stringify({ body }),
    });
    setBody("");
    await onReload();
    const next = await api<Comment[]>(`/api/tasks/${task.id}/comments/`);
    setComments(next);
  }

  return (
    <div className="drawer-scrim" onClick={onClose}>
      <aside className="drawer" onClick={(event) => event.stopPropagation()}>
        <header className="drawer-head">
          <div>
            <p className="muted">#{task.id}</p>
            <h2>{task.title}</h2>
          </div>
          <button className="ghost small" type="button" onClick={onClose}>
            Close
          </button>
        </header>
        <label className="field">
          <span>Description</span>
          <textarea
            rows={4}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            onBlur={() => {
              if (description !== task.description) onPatch({ description });
            }}
          />
        </label>
        <div className="grid-2 tight">
          <label className="field">
            <span>Status</span>
            <select value={task.status} onChange={(e) => onPatch({ status: e.target.value })}>
              {COLUMNS.map((col) => (
                <option key={col.key} value={col.key}>
                  {col.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Priority</span>
            <select value={task.priority} onChange={(e) => onPatch({ priority: e.target.value })}>
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Assignee</span>
            <select
              value={task.assignee ?? ""}
              onChange={(e) => onPatch({ assignee: e.target.value ? Number(e.target.value) : null })}
            >
              <option value="">Unassigned</option>
              {members.map((member) => (
                <option key={member.user_id} value={member.user_id}>
                  {member.email}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Due</span>
            <input
              type="date"
              value={task.due_date ?? ""}
              onChange={(e) => onPatch({ due_date: e.target.value || null })}
            />
          </label>
        </div>
        <div>
          <p className="field">
            <span>Labels</span>
          </p>
          <div className="row">
            {labels.map((lab) => {
              const on = task.labels.some((item) => item.id === lab.id);
              return (
                <button
                  key={lab.id}
                  type="button"
                  className={`chip-btn${on ? " on" : ""}`}
                  style={{ background: on ? lab.color : "transparent", borderColor: lab.color }}
                  onClick={() => {
                    const next = on
                      ? task.labels.filter((item) => item.id !== lab.id).map((item) => item.id)
                      : [...task.labels.map((item) => item.id), lab.id];
                    onPatch({ label_ids: next });
                  }}
                >
                  {lab.name}
                </button>
              );
            })}
          </div>
        </div>
        <section>
          <h3>Comments</h3>
          <ul className="comments">
            {comments.map((comment) => (
              <li key={comment.id}>
                <strong>{comment.author_email ?? "Someone"}</strong>
                <p>{comment.body}</p>
              </li>
            ))}
          </ul>
          <form className="stack" onSubmit={(event) => void onComment(event)}>
            <textarea
              rows={3}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="Write a note"
              required
            />
            <button type="submit">Comment</button>
          </form>
        </section>
      </aside>
    </div>
  );
}
