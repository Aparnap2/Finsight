"use client";

import { useEffect, useState } from "react";
import { VarianceHeatmap } from "@/components/VarianceHeatmap";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Variance {
  account_id: string;
  account_name: string;
  department: string;
  actual_amount: number;
  budget_amount: number;
  variance_amount: number;
  variance_pct: number;
  is_material: boolean;
}

export default function VariancePage() {
  const [variances, setVariances] = useState<Variance[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/pipeline/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ period: "2026-06", entity_id: "CF001", run_sync: true }),
    })
      .then((r) => r.json())
      .then((data) => {
        setVariances(data.variances || []);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  if (loading) return <div className="p-8">Loading variances...</div>;
  if (error) return <div className="p-8 text-red-600">Error: {error}</div>;

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Variance Heatmap</h1>
      <p className="text-gray-500 mb-4">
        {variances.length} accounts, {variances.filter((v) => v.is_material).length} material
      </p>
      <VarianceHeatmap variances={variances} />
    </div>
  );
}
