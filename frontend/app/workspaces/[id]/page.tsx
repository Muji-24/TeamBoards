"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import {
  type Dashboard,
  type Label,
  type Project,
  type Workspace,
  api,
  errorMessage,
} from "@/lib/api";
import { Shell } from "../../ui";

export default function WorkspacePage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [labels, setLabels] = useState<Label[]>([]);
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [projectName, setProjectName] = useState("");
  const [memberEmail, setMemberEmail] = useState("");
  const [labelName, setLabelName] = useState("");

  async function load() {
    try {
      const [ws, projs, labs, board] = await Promise.all([
        api<Workspace>(`/api/workspaces/${id}/`),
        api<Project[]>(`/api/projects/?workspace=${id}`),
        api<Label[]>(`/api/labels/?workspace=${id}`),
        api<Dashboard>(`/api/workspaces/${id}/dashboard/`),
      ]);
      setWorkspace(ws);
      setProjects(projs);
      setLabels(labs);
      setDash(board);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  useEffect(() => {
    void load();
  }, [id]);

  async function onCreateProject(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      await api("/api/projects/", {
        method: "POST",
        body: JSON.stringify({ workspace: Number(id), name: projectName }),
      });
      setProjectName("");
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function onAddMember(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      await api(`/api/workspaces/${id}/add_member/`, {
        method: "POST",
        body: JSON.stringify({ email: memberEmail }),
      });
      setMemberEmail("");
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function onAddLabel(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      await api("/api/labels/", {
        method: "POST",
        body: JSON.stringify({ workspace: Number(id), name: labelName, color: "#66707f" }),
      });
      setLabelName("");
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const counts = dash?.counts;

  return (
    <Shell>
      <p className="crumb">
        <Link href="/">Workspaces</Link>
        {workspace ? ` / ${workspace.name}` : ""}
      </p>
      <div className="page-head">
        <div>
          <h1>{workspace?.name ?? "Workspace"}</h1>
          <p className="lede muted">Boards, people, labels, and a live activity feed.</p>
        </div>
      </div>
      {error ? <p className="error">{error}</p> : null}

      {counts ? (
        <div className="stats">
          <div className="stat">
            <strong>{counts.todo}</strong>
            <span>To do</span>
          </div>
          <div className="stat">
            <strong>{counts.doing}</strong>
            <span>Doing</span>
          </div>
          <div className="stat">
            <strong>{counts.done}</strong>
            <span>Done</span>
          </div>
          <div className="stat warn">
            <strong>{counts.overdue}</strong>
            <span>Overdue</span>
          </div>
          <div className="stat">
            <strong>{counts.unassigned}</strong>
            <span>Unassigned</span>
          </div>
        </div>
      ) : null}

      <div className="grid-2">
        <section className="card">
          <h2>Boards</h2>
          <form className="row" onSubmit={onCreateProject}>
            <input
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="e.g. Website relaunch"
              required
            />
            <button type="submit">Add</button>
          </form>
          <div className="workspace-grid" style={{ marginTop: 16 }}>
            {projects.map((p) => (
              <Link key={p.id} href={`/projects/${p.id}`} className="project-card">
                <span className="project-mark">{p.name.slice(0, 1).toUpperCase()}</span>
                <strong>{p.name}</strong>
                <footer>
                  <span className="muted">{p.open_count} open</span>
                </footer>
              </Link>
            ))}
          </div>
          {projects.length === 0 ? (
            <p className="muted" style={{ marginTop: 14 }}>
              No boards yet. Add one above.
            </p>
          ) : null}
        </section>

        <div className="stack">
          {workspace?.my_role === "owner" ? (
            <section className="card">
              <h2>Members</h2>
              <p className="muted">They need an account first. You stay owner in Django.</p>
              <ul className="members">
                {workspace.members.map((m) => (
                  <li key={m.id}>
                    {m.email} <span className="pill">{m.role}</span>
                  </li>
                ))}
              </ul>
              <form className="row" onSubmit={onAddMember}>
                <input
                  type="email"
                  value={memberEmail}
                  onChange={(e) => setMemberEmail(e.target.value)}
                  placeholder="teammate@email"
                  required
                />
                <button type="submit">Invite</button>
              </form>
            </section>
          ) : (
            <section className="card">
              <h2>Your role</h2>
              <p className="muted">Member — you can work boards, not invite people.</p>
            </section>
          )}

          <section className="card">
            <h2>Labels</h2>
            <div className="row" style={{ marginBottom: 12 }}>
              {labels.map((lab) => (
                <span key={lab.id} className="chip" style={{ background: lab.color }}>
                  {lab.name}
                </span>
              ))}
            </div>
            {workspace?.my_role === "owner" ? (
              <form className="row" onSubmit={onAddLabel}>
                <input
                  value={labelName}
                  onChange={(e) => setLabelName(e.target.value)}
                  placeholder="New label"
                  required
                />
                <button type="submit">Add</button>
              </form>
            ) : null}
          </section>
        </div>
      </div>

      <section className="card" style={{ marginTop: 16 }}>
        <h2>Activity</h2>
        {dash?.activity.length ? (
          <ul className="activity">
            {dash.activity.map((item) => (
              <li key={item.id}>
                <span>{item.summary}</span>
                <span className="muted">
                  {item.actor_email ?? "system"} · {item.created_at.slice(0, 16).replace("T", " ")}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">Nothing has happened yet.</p>
        )}
      </section>
    </Shell>
  );
}
