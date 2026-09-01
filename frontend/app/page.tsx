"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";

import { type Workspace, api, errorMessage } from "@/lib/api";
import { Shell } from "./ui";

export default function HomePage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [error, setError] = useState("");
  const [name, setName] = useState("");

  async function load() {
    try {
      const data = await api<Workspace[]>("/api/workspaces/");
      setWorkspaces(data);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      await api("/api/workspaces/", {
        method: "POST",
        body: JSON.stringify({ name }),
      });
      setName("");
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Shell>
      <div className="page-head">
        <div>
          <p className="crumb">Home</p>
          <h1>Workspaces</h1>
          <p className="lede muted">A team lives here. Creating one makes you the owner in Django.</p>
        </div>
        <form className="row" onSubmit={onCreate}>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Studio name"
            required
          />
          <button type="submit">New workspace</button>
        </form>
      </div>
      {error ? <p className="error">{error}</p> : null}
      {workspaces.length === 0 ? (
        <div className="empty">
          <h2>Nothing here yet</h2>
          <p className="muted">Create a workspace, then add a board you can talk to.</p>
        </div>
      ) : (
        <div className="workspace-grid">
          {workspaces.map((ws) => (
            <Link key={ws.id} href={`/workspaces/${ws.id}`} className="workspace-card">
              <span className="workspace-mark">{ws.name.slice(0, 1).toUpperCase()}</span>
              <strong>{ws.name}</strong>
              <footer>
                <span className="muted">
                  {ws.project_count} board{ws.project_count === 1 ? "" : "s"} · {ws.task_count}{" "}
                  task{ws.task_count === 1 ? "" : "s"}
                </span>
                <span className="pill">{ws.my_role}</span>
              </footer>
            </Link>
          ))}
        </div>
      )}
    </Shell>
  );
}
