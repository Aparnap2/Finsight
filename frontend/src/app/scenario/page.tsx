"use client";

import { useEffect, useState } from "react";
import { ScenarioCard } from "@/components/ScenarioCard";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface RootCause {
  variance_id: string;
  summary: string;
  confidence_score: number;
  recommended_action: string;
}

export default function ScenarioPage() {
  const [rootCauses, setRootCauses] = useState<RootCause[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/pipeline/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ period: "2026-06", entity_id: "CF001", run_sync: true }),
    })
      .then((r) => r.json())
      .then((data) => {
        setRootCauses(data.root_causes || []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-8">Loading scenarios...</div>;

  const scenarios = rootCauses.map((rc) => ({
    name: `Mitigation: ${rc.summary.slice(0, 50)}...`,
    description: rc.recommended_action || "No action recommended",
    revenue_impact: 0,
    ebitda_impact: 0,
    cash_impact: 0,
    probability_assessment: `Confidence: ${(rc.confidence_score * 100).toFixed(0)}%`,
  }));

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Scenario Explorer</h1>
      <p className="text-gray-500 mb-4">
        {scenarios.length} scenarios from root-cause findings
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {scenarios.map((s, i) => (
          <ScenarioCard key={i} scenario={s} />
        ))}
      </div>
    </div>
  );
}
