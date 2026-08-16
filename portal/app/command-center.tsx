"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import Launchpad from "./launchpad";

type Project = { id: string; name: string; quota?: Record<string, number> };
type Resource = {
  id: string;
  project_id: string;
  name: string;
  kind: string;
  state: string;
  generation: number;
  observed_generation: number;
  spec: Record<string, unknown>;
  status: Record<string, unknown>;
};
type Operation = { id: string; resource_id: string; action: string; state: string; attempts: number; updated_at: string };
type AuditEvent = { id: string; actor: string; action: string; outcome: string; created_at: string };
type Connection = { controlUrl: string; aiUrl: string; launchpadUrl: string; token: string };

const resourceTemplates: Record<string, string> = {
  service: '{"image":"ghcr.io/example/support-api:0.1.0","replicas":1,"port":8080}',
  database: '{"engine":"postgres","resources":{"cpu":1,"memory_mb":512,"gpu":0}}',
  model: '{"model_id":"Qwen/Qwen2.5-1.5B-Instruct","resources":{"cpu":2,"memory_mb":2048,"gpu":0}}',
  knowledge_base: '{"source":"docs/runbooks"}',
  agent: '{"tools":["health.read"]}',
  job: '{"command":["python","-m","titan_api"]}',
};

const demoProjects: Project[] = [
  { id: "prj_demo", name: "production" },
  { id: "prj_lab", name: "learning-lab" },
];

const demoResources: Resource[] = [
  { id: "res_payments", project_id: "prj_demo", name: "payments-api", kind: "service", state: "READY", generation: 3, observed_generation: 3, spec: { replicas: 3 }, status: {} },
  { id: "res_model", project_id: "prj_demo", name: "support-model", kind: "model", state: "READY", generation: 1, observed_generation: 1, spec: { accelerator: "A10", vram: "42%" }, status: {} },
  { id: "res_docs", project_id: "prj_demo", name: "support-docs", kind: "knowledge_base", state: "UPDATING", generation: 8, observed_generation: 7, spec: { sources: 1284 }, status: {} },
];

const demoOperations: Operation[] = [
  { id: "op_1", resource_id: "res_docs", action: "APPLY", state: "RUNNING", attempts: 1, updated_at: "2026-08-16T09:42:00Z" },
  { id: "op_2", resource_id: "res_payments", action: "APPLY", state: "SUCCEEDED", attempts: 1, updated_at: "2026-08-16T09:31:00Z" },
];

const demoAudit: AuditEvent[] = [
  { id: "evt_1", actor: "system:reconciler", action: "operation:apply", outcome: "succeeded", created_at: "2026-08-16T09:31:00Z" },
  { id: "evt_2", actor: "bootstrap-admin", action: "resource:create", outcome: "allowed", created_at: "2026-08-16T09:30:55Z" },
];

function apiHeaders(connection: Connection, includeBody = false): HeadersInit {
  return { Authorization: `Bearer ${connection.token}`, ...(includeBody ? { "Content-Type": "application/json" } : {}) };
}

async function readJson<T>(response: Response): Promise<T> {
  const document = await response.json();
  if (!response.ok) throw new Error(document?.error?.message ?? `Request failed with ${response.status}`);
  return document as T;
}

function displayTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "--:--" : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

export default function CommandCenter() {
  const [connection, setConnection] = useState<Connection | null>(null);
  const [projects, setProjects] = useState<Project[]>(demoProjects);
  const [selectedProject, setSelectedProject] = useState(demoProjects[0].id);
  const [resources, setResources] = useState<Resource[]>(demoResources);
  const [operations, setOperations] = useState<Operation[]>(demoOperations);
  const [audit, setAudit] = useState<AuditEvent[]>(demoAudit);
  const [budget, setBudget] = useState({ used: 38200, limit: 100000, remaining: 61800 });
  const [activeView, setActiveView] = useState("overview");
  const [connectOpen, setConnectOpen] = useState(false);
  const [resourceOpen, setResourceOpen] = useState(false);
  const [projectOpen, setProjectOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("Demo telemetry loaded");
  const [error, setError] = useState("");
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [kindFilter, setKindFilter] = useState("all");
  const [resourceKind, setResourceKind] = useState("service");
  const [resourceSpec, setResourceSpec] = useState(resourceTemplates.service);

  const refresh = useCallback(async (target: Connection) => {
    setBusy(true);
    setError("");
    try {
      const projectDocument = await readJson<{ items: Project[] }>(await fetch(`${target.controlUrl}/v1/projects`, { headers: apiHeaders(target) }));
      const nextProjects = projectDocument.items;
      const projectId = nextProjects.some((project) => project.id === selectedProject) ? selectedProject : nextProjects[0]?.id ?? "";
      const resourceBatches = await Promise.all(nextProjects.map(async (project) => {
        const value = await readJson<{ items: Resource[] }>(await fetch(`${target.controlUrl}/v1/projects/${project.id}/resources`, { headers: apiHeaders(target) }));
        return value.items;
      }));
      const [operationDocument, auditDocument] = await Promise.all([
        fetch(`${target.controlUrl}/v1/operations`, { headers: apiHeaders(target) }).then((response) => response.ok ? response.json() : { items: [] }),
        fetch(`${target.controlUrl}/v1/audit?limit=20`, { headers: apiHeaders(target) }).then((response) => response.ok ? response.json() : { items: [] }),
      ]);
      let nextBudget = { used: 0, limit: 0, remaining: 0 };
      if (projectId) {
        const response = await fetch(`${target.aiUrl}/v1/budgets`, { method: "POST", headers: apiHeaders(target, true), body: JSON.stringify({ project_id: projectId }) });
        if (response.ok) nextBudget = await response.json();
      }
      setProjects(nextProjects);
      setSelectedProject(projectId);
      setResources(resourceBatches.flat());
      setOperations(operationDocument.items ?? []);
      setAudit(auditDocument.items ?? []);
      setBudget(nextBudget);
      setLastRefresh(new Date());
      setNotice("Live state synchronized");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Connection failed");
      throw requestError;
    } finally {
      setBusy(false);
    }
  }, [selectedProject]);

  useEffect(() => {
    if (!connection) return;
    const timer = window.setInterval(() => void refresh(connection), 15000);
    return () => window.clearInterval(timer);
  }, [connection, refresh]);

  const filteredResources = useMemo(() => resources.filter((resource) => resource.project_id === selectedProject && (kindFilter === "all" || resource.kind === kindFilter)), [resources, selectedProject, kindFilter]);
  const pendingOperations = operations.filter((operation) => !["SUCCEEDED", "FAILED"].includes(operation.state));
  const failedResources = resources.filter((resource) => resource.state === "FAILED");
  const budgetPercent = budget.limit ? Math.min(100, Math.round((budget.used / budget.limit) * 100)) : 0;

  async function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const target = { controlUrl: String(form.get("controlUrl") ?? "").replace(/\/$/, ""), aiUrl: String(form.get("aiUrl") ?? "").replace(/\/$/, ""), launchpadUrl: String(form.get("launchpadUrl") ?? "").replace(/\/$/, ""), token: String(form.get("token") ?? "") };
    try {
      await refresh(target);
      setConnection(target);
      setConnectOpen(false);
    } catch {
      // Error state is rendered in the connection dialog.
    }
  }

  async function createProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = String(new FormData(event.currentTarget).get("name") ?? "").trim();
    if (!name) return;
    setBusy(true);
    try {
      if (!connection) {
        const item = { id: `prj_${crypto.randomUUID().replaceAll("-", "")}`, name };
        setProjects((current) => [...current, item]);
        setSelectedProject(item.id);
      } else {
        const project = await readJson<Project>(await fetch(`${connection.controlUrl}/v1/projects`, { method: "POST", headers: { ...apiHeaders(connection, true), "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ name }) }));
        await refresh(connection);
        setSelectedProject(project.id);
      }
      setProjectOpen(false);
      setNotice(`Project ${name} created`);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Project creation failed");
    } finally {
      setBusy(false);
    }
  }

  async function createResource(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProject) return setError("Create a project before creating a resource");
    const form = new FormData(event.currentTarget);
    const name = String(form.get("name") ?? "").trim();
    const kind = String(form.get("kind") ?? "service");
    try {
      const spec = JSON.parse(String(form.get("spec") ?? "{}")) as Record<string, unknown>;
      setBusy(true);
      if (!connection) {
        const item: Resource = { id: `res_${crypto.randomUUID().replaceAll("-", "")}`, project_id: selectedProject, name, kind, state: "PENDING", generation: 1, observed_generation: 0, spec, status: {} };
        setResources((current) => [...current, item]);
      } else {
        await readJson<Resource>(await fetch(`${connection.controlUrl}/v1/projects/${selectedProject}/resources`, { method: "POST", headers: { ...apiHeaders(connection, true), "Idempotency-Key": crypto.randomUUID() }, body: JSON.stringify({ name, kind, spec }) }));
        await refresh(connection);
      }
      setResourceOpen(false);
      setNotice(`${kind} ${name} accepted`);
      setError("");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Resource creation failed");
    } finally {
      setBusy(false);
    }
  }

  async function reconcile() {
    if (!connection) {
      setResources((current) => current.map((resource) => resource.state === "PENDING" ? { ...resource, state: "READY", observed_generation: resource.generation } : resource));
      setNotice("Demo reconciliation completed");
      return;
    }
    setBusy(true);
    try {
      await readJson(await fetch(`${connection.controlUrl}/v1/reconcile`, { method: "POST", headers: apiHeaders(connection, true), body: JSON.stringify({ limit: 20 }) }));
      await refresh(connection);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Reconciliation failed");
    } finally {
      setBusy(false);
    }
  }

  const views = [["overview", "01", "Overview"], ["resources", "02", "Resources"], ["operations", "03", "Operations"], ["security", "04", "Security"], ["launchpad", "05", "Launchpad"]];

  return (
    <main className="shell">
      <aside className="rail">
        <div className="brand-mark">T</div>
        <nav aria-label="Primary navigation">
          {views.map(([view, number, label]) => <button className={`rail-link ${activeView === view ? "active" : ""}`} type="button" aria-label={label} onClick={() => setActiveView(view)} key={view}>{number}</button>)}
        </nav>
        <span className={`rail-status ${connection ? "live" : "demo"}`} title={connection ? "Live control plane" : "Demo mode"} />
      </aside>

      <section className="workspace" id="overview">
        <header className="topbar">
          <div><p className="eyebrow">Project Titan / {activeView === "launchpad" ? "multi-cloud planning" : projects.find((item) => item.id === selectedProject)?.name ?? "no project"}</p><h1>{activeView === "overview" ? "Command center" : activeView === "launchpad" ? "Cloud launchpad" : activeView}</h1></div>
          <div className="top-actions">
            <button className="health-pill" type="button" onClick={() => setConnectOpen(true)}><i className={connection ? "connected" : ""} /> {connection ? "Live control plane" : "Demo mode · connect"}</button>
            {activeView !== "launchpad" && <button className="primary-button" type="button" onClick={() => setResourceOpen(true)}>Create resource</button>}
          </div>
        </header>

        {activeView !== "launchpad" && <div className="context-bar">
          <label>Project<select value={selectedProject} onChange={(event) => setSelectedProject(event.target.value)}>{projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}</select></label>
          <button className="quiet-button" type="button" onClick={() => setProjectOpen(true)}>+ New project</button>
          <span>{busy ? "Synchronizing…" : `${notice} · ${lastRefresh ? lastRefresh.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "preview ready"}`}</span>
          <button className="quiet-button" type="button" disabled={busy || !connection} onClick={() => connection && refresh(connection)}>Refresh</button>
        </div>}
        {error && <div className="error-banner" role="alert">{error}<button type="button" onClick={() => setError("")}>Dismiss</button></div>}

        {(activeView === "overview" || activeView === "resources") && <>
          <section className="signal-grid" aria-label="Platform summary">
            <article className="signal-card emphasis"><span className="signal-label">Platform state</span><strong>{failedResources.length ? "Degraded" : connection ? "Healthy" : "99.97%"}</strong><small>{connection ? "Current desired-state health" : "Demo 30-day SLO · 21m budget"}</small></article>
            <article className="signal-card"><span className="signal-label">Active resources</span><strong>{resources.filter((resource) => resource.state !== "DELETED").length}</strong><small>Across {projects.length} project{projects.length === 1 ? "" : "s"}</small></article>
            <article className="signal-card"><span className="signal-label">Pending operations</span><strong>{pendingOperations.length}</strong><small>{failedResources.length} failed resources</small></article>
          </section>

          <section className="lower-grid" id="resources">
            <article className="panel resource-panel">
              <div className="panel-heading"><div><p className="eyebrow">Desired vs observed</p><h2>Platform resources</h2></div><select className="compact-select" value={kindFilter} onChange={(event) => setKindFilter(event.target.value)} aria-label="Resource kind filter"><option value="all">All kinds</option><option value="service">Services</option><option value="database">Databases</option><option value="model">Models</option><option value="knowledge_base">Knowledge</option><option value="agent">Agents</option><option value="job">Jobs</option></select></div>
              <div className="resource-list">
                {filteredResources.length === 0 && <p className="empty-state">No resources match this project and filter.</p>}
                {filteredResources.map((resource) => <div className="resource-row" key={resource.id}><span className={`state-dot ${resource.state.toLowerCase()}`} /><div className="resource-name"><strong>{resource.name}</strong><span>{resource.kind.replaceAll("_", " ")}</span></div><span className="resource-detail">gen {resource.observed_generation}/{resource.generation}</span><span className={`state-label ${resource.state.toLowerCase()}`}>{resource.state}</span></div>)}
              </div>
            </article>

            <article className="panel autonomy-panel" id="operations">
              <div className="panel-heading"><div><p className="eyebrow">Agent operations</p><h2>Autonomy boundary</h2></div><span className="level-badge">Level 1</span></div>
              <p className="autonomy-copy">Titan SRE can investigate and recommend. Production changes require explicit approval.</p>
              <div className="policy-track" aria-label="Autonomy level 1 of 5">{[0, 1, 2, 3, 4, 5].map((level) => <span className={level <= 1 ? "filled" : ""} key={level}>{level}</span>)}</div>
              <div className="agent-event"><span className="event-time">POLICY</span><p><strong>Read-only investigation enabled</strong><br />No autonomous mutation authority</p></div>
              <button className="panel-action" type="button" onClick={reconcile} disabled={busy}>Run reconciliation</button>
            </article>
          </section>
        </>}

        {(activeView === "overview" || activeView === "operations") && <section className="operations-grid">
          <article className="panel"><div className="panel-heading"><div><p className="eyebrow">Controller queue</p><h2>Recent operations</h2></div><span className="level-badge">{operations.length}</span></div><div className="timeline">{operations.slice(0, 8).map((operation) => <div className="timeline-row" key={operation.id}><span>{displayTime(operation.updated_at)}</span><strong>{operation.action.toLowerCase()} · {operation.resource_id.slice(0, 18)}</strong><em className={operation.state.toLowerCase()}>{operation.state}</em></div>)}{operations.length === 0 && <p className="empty-state">The operation queue is empty.</p>}</div></article>
          <article className="panel budget-panel"><div className="panel-heading"><div><p className="eyebrow">AI guardrail</p><h2>Token consumption</h2></div></div><div className="budget-ring" style={{ "--progress": `${budgetPercent * 3.6}deg` } as React.CSSProperties}><strong>{budgetPercent}%</strong><span>used</span></div><p>{budget.used.toLocaleString()} of {budget.limit.toLocaleString()} tokens reserved for this runtime.</p></article>
        </section>}

        {(activeView === "overview" || activeView === "security") && <section className="security-section" id="security">
          <div className="section-heading"><div><p className="eyebrow">Continuous controls</p><h2>Security posture</h2></div><span>Restricted baseline</span></div>
          <div className="control-grid"><article><span>Identity</span><strong>Bootstrap + JWT</strong><small>Constant-time token hashes · strict claims</small></article><article><span>Workloads</span><strong>Restricted</strong><small>Non-root · read-only · no capabilities</small></article><article><span>Network</span><strong>Default deny</strong><small>Explicit ingress · DNS-only egress</small></article><article><span>Audit denials</span><strong>{audit.filter((event) => event.outcome === "denied").length}</strong><small>Immutable append-only sequence</small></article></div>
          <div className="audit-strip">{audit.slice(0, 5).map((event) => <div key={event.id}><span>{displayTime(event.created_at)}</span><strong>{event.actor}</strong><em>{event.action}</em><b className={event.outcome}>{event.outcome}</b></div>)}</div>
        </section>}
        {activeView === "launchpad" && <Launchpad connection={connection ? { launchpadUrl: connection.launchpadUrl, token: connection.token } : null} />}
      </section>

      {connectOpen && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setConnectOpen(false)}><section className="modal" role="dialog" aria-modal="true" aria-labelledby="connect-title"><p className="eyebrow">Local secure session</p><h2 id="connect-title">Connect Titan APIs</h2><p className="modal-copy">The token stays in memory and is cleared when this page reloads. Default URLs are localhost-only.</p><form onSubmit={connect}><label>Control API<input name="controlUrl" type="url" defaultValue="http://localhost:8090" required /></label><label>AI API<input name="aiUrl" type="url" defaultValue="http://localhost:8100" required /></label><label>Launchpad API<input name="launchpadUrl" type="url" defaultValue="http://localhost:8300" required /></label><label>Admin token<input name="token" type="password" minLength={24} autoComplete="off" required /></label><div className="modal-actions"><button className="quiet-button" type="button" onClick={() => setConnectOpen(false)}>Cancel</button><button className="primary-button" type="submit" disabled={busy}>Connect</button></div></form></section></div>}
      {projectOpen && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setProjectOpen(false)}><section className="modal compact" role="dialog" aria-modal="true" aria-labelledby="project-title"><p className="eyebrow">Isolation boundary</p><h2 id="project-title">Create project</h2><form onSubmit={createProject}><label>Project name<input name="name" pattern="[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?" placeholder="learning-lab" required /></label><div className="modal-actions"><button className="quiet-button" type="button" onClick={() => setProjectOpen(false)}>Cancel</button><button className="primary-button" type="submit">Create</button></div></form></section></div>}
      {resourceOpen && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setResourceOpen(false)}><section className="modal" role="dialog" aria-modal="true" aria-labelledby="resource-title"><p className="eyebrow">Desired state</p><h2 id="resource-title">Create resource</h2><form onSubmit={createResource}><label>Name<input name="name" pattern="[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?" placeholder="support-api" required /></label><label>Kind<select name="kind" value={resourceKind} onChange={(event) => { const kind = event.target.value; setResourceKind(kind); setResourceSpec(resourceTemplates[kind]); }}><option value="service">Service</option><option value="database">Database</option><option value="model">Model</option><option value="knowledge_base">Knowledge base</option><option value="agent">Agent</option><option value="job">Job</option></select></label><label>Specification<textarea name="spec" value={resourceSpec} onChange={(event) => setResourceSpec(event.target.value)} rows={5} spellCheck={false} required /></label><div className="modal-actions"><button className="quiet-button" type="button" onClick={() => setResourceOpen(false)}>Cancel</button><button className="primary-button" type="submit" disabled={busy}>Submit desired state</button></div></form></section></div>}
    </main>
  );
}
