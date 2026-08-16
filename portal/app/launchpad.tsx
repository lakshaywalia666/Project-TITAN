"use client";

import { FormEvent, useState } from "react";

type LaunchpadConnection = { launchpadUrl: string; token: string } | null;
type Recommendation = {
  provider: "aws" | "azure" | "gcp";
  provider_name: string;
  score: number;
  region: string;
  compute_service: string;
  reasons: string[];
  warnings: string[];
  blockers: string[];
  cost: { cost_band: string; calculator_url: string; estimate_usd_month: null };
};
type Assessment = {
  id: string;
  deployment_readiness: string;
  recommended_provider: string;
  blockers: string[];
  warnings: string[];
  recommendations: Recommendation[];
};
type Plan = {
  id: string;
  provider_name: string;
  status: string;
  cloud_mutation_performed: boolean;
  credentials_policy: string;
  resources: { service_name: string; purpose: string }[];
  preflight_checks: string[];
  next_action: string;
};

const providerNames = { aws: "Amazon Web Services", azure: "Microsoft Azure", gcp: "Google Cloud" };
const computeNames = { aws: "AWS App Runner", azure: "Azure Container Apps", gcp: "Google Cloud Run" };

function demoAssessment(hasImage: boolean, hasBudget: boolean): Assessment {
  const blockers = [
    ...(!hasImage ? ["Add an immutable public GHCR image pinned with @sha256."] : []),
    ...(!hasBudget ? ["Set a reviewed non-zero monthly budget ceiling."] : []),
  ];
  const scores = { gcp: 89, azure: 87, aws: 81 } as const;
  return {
    id: "asm_demo_preview",
    deployment_readiness: blockers.length ? "BLOCKED" : "READY_FOR_PROVIDER_SELECTION",
    recommended_provider: "gcp",
    blockers,
    warnings: ["Preview only: no cloud resource or dollar estimate was created."],
    recommendations: (["gcp", "azure", "aws"] as const).map((provider) => ({
      provider,
      provider_name: providerNames[provider],
      score: scores[provider],
      region: provider === "gcp" ? "asia-south1" : provider === "azure" ? "centralindia" : "ap-south-1",
      compute_service: computeNames[provider],
      reasons: [`${computeNames[provider]} fits a managed containerized HTTP application.`],
      warnings: ["Verify current pricing and free-tier eligibility in the official calculator."],
      blockers: [],
      cost: { cost_band: "LOW", calculator_url: "#", estimate_usd_month: null },
    })),
  };
}

export default function Launchpad({ connection }: { connection: LaunchpadConnection }) {
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function assess(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setPlan(null);
    const form = new FormData(event.currentTarget);
    const document = {
      name: String(form.get("name") ?? ""),
      repository_url: String(form.get("repository_url") ?? ""),
      image: String(form.get("image") ?? ""),
      container_port: Number(form.get("container_port") ?? 8080),
      health_path: String(form.get("health_path") ?? "/healthz"),
      environment: String(form.get("environment") ?? "development"),
      geography: String(form.get("geography") ?? "india"),
      monthly_requests: Number(form.get("monthly_requests") ?? 10000),
      cpu_millicores: 500,
      memory_mb: 512,
      min_instances: 0,
      max_instances: 3,
      scale_to_zero: true,
      public_access: true,
      database: form.get("database") ? "postgresql" : "none",
      object_storage: form.get("object_storage") === "on",
      background_worker: false,
      availability: "standard",
      data_classification: "internal",
      budget_usd_month: Number(form.get("budget_usd_month") ?? 0),
    };
    try {
      if (!connection) {
        setAssessment(demoAssessment(Boolean(document.image), document.budget_usd_month > 0));
      } else {
        const response = await fetch(`${connection.launchpadUrl}/v1/assessments`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${connection.token}`,
            "Content-Type": "application/json",
            "Idempotency-Key": crypto.randomUUID(),
          },
          body: JSON.stringify(document),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result?.error?.message ?? `Assessment failed with ${response.status}`);
        setAssessment(result as Assessment);
      }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Assessment failed");
    } finally {
      setBusy(false);
    }
  }

  async function generatePlan(provider: Recommendation["provider"]) {
    if (!assessment || !connection) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${connection.launchpadUrl}/v1/assessments/${assessment.id}/plans`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${connection.token}`,
          "Content-Type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify({ provider }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result?.error?.message ?? `Plan failed with ${response.status}`);
      setPlan(result as Plan);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Plan generation failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="launchpad" aria-label="Cloud Launchpad">
      <div className="launchpad-intro">
        <div><p className="eyebrow">AWS · Azure · Google Cloud</p><h2>Cloud Launchpad</h2></div>
        <span className="level-badge">{connection ? "Live planner" : "Safe demo"}</span>
        <p>Describe one containerized HTTP application. TITAN ranks managed cloud services, explains the trade-offs, and produces a guarded dry-run plan. It never deploys from this screen.</p>
      </div>

      <form className="launchpad-form" onSubmit={assess}>
        <label>Project name<input name="name" defaultValue="support-api" pattern="[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?" required /></label>
        <label>GitHub repository<input name="repository_url" type="url" defaultValue="https://github.com/example/support-api" required /></label>
        <label className="wide">Immutable GHCR image<input name="image" placeholder="ghcr.io/owner/app@sha256:…" /></label>
        <label>Container port<input name="container_port" type="number" defaultValue="8080" min="1" max="65535" required /></label>
        <label>Health path<input name="health_path" defaultValue="/healthz" required /></label>
        <label>Environment<select name="environment" defaultValue="development"><option value="development">Development</option><option value="staging">Staging</option><option value="production">Production</option></select></label>
        <label>Data geography<select name="geography" defaultValue="india"><option value="india">India</option><option value="us">United States</option><option value="europe">Europe</option><option value="global">Global</option></select></label>
        <label>Monthly requests<input name="monthly_requests" type="number" defaultValue="10000" min="0" /></label>
        <label>Budget ceiling (USD)<input name="budget_usd_month" type="number" defaultValue="0" min="0" step="0.01" /></label>
        <label className="check"><input name="database" type="checkbox" /> Managed PostgreSQL</label>
        <label className="check"><input name="object_storage" type="checkbox" /> Object storage</label>
        <button className="primary-button" type="submit" disabled={busy}>{busy ? "Analyzing…" : "Compare clouds"}</button>
      </form>

      {error && <div className="error-banner" role="alert">{error}</div>}
      {assessment && <>
        <div className={`readiness ${assessment.blockers.length ? "blocked" : "ready"}`}><strong>{assessment.deployment_readiness.replaceAll("_", " ")}</strong><span>Recommended: {assessment.recommended_provider.toUpperCase()}</span></div>
        {assessment.blockers.length > 0 && <div className="launchpad-blockers"><p className="eyebrow">Resolve before credentials</p>{assessment.blockers.map((item) => <p key={item}>× {item}</p>)}</div>}
        <div className="provider-grid">
          {assessment.recommendations.map((item) => <article className="provider-card" key={item.provider}>
            <div><span>{item.provider.toUpperCase()}</span><strong>{item.score}/100</strong></div>
            <h3>{item.compute_service}</h3>
            <p>{item.reasons[0]}</p>
            <dl><div><dt>Region</dt><dd>{item.region}</dd></div><div><dt>Cost shape</dt><dd>{item.cost.cost_band}</dd></div></dl>
            <small>No dollar estimate · official calculator required</small>
            <button className="panel-action" type="button" onClick={() => generatePlan(item.provider)} disabled={busy || !connection}>{connection ? "Generate dry-run plan" : "Connect APIs for plan"}</button>
          </article>)}
        </div>
      </>}
      {plan && <article className="plan-result"><div><p className="eyebrow">No mutation performed</p><h2>{plan.provider_name} plan · {plan.status}</h2></div><p>{plan.next_action}</p><div className="plan-services">{plan.resources.map((resource) => <span key={resource.service_name}>{resource.service_name}</span>)}</div><small>Identity: {plan.credentials_policy.replaceAll("_", " ")}</small></article>}
    </section>
  );
}
