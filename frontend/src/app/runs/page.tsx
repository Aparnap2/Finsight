"use client";

import { useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function RunsPage() {
  const [runs, setRuns] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/pipeline/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ period: "2026-06", entity_id: "CF001", run_sync: true }),
    })
      .then((r) => r.json())
      .then((data) => {
        setRuns([{
          run_id: data.run_id,
          status: data.status,
          period: data.period,
          material_count: data.material_count,
          variances_count: data.variances?.length || 0,
        }]);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-8">Loading runs...</div>;

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Pipeline Runs</h1>
      <table className="min-w-full border-collapse bg-white rounded-lg shadow">
        <thead>
          <tr className="bg-gray-100">
            <th className="border p-3 text-left">Run ID</th>
            <th className="border p-3 text-left">Period</th>
            <th className="border p-3 text-left">Status</th>
            <th className="border p-3 text-right">Variances</th>
            <th className="border p-3 text-right">Material</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.run_id}>
              <td className="border p-3 font-mono text-sm">{run.run_id}</td>
              <td className="border p-3">{run.period}</td>
              <td className="border p-3">
                <span className={`px-2 py-1 rounded text-sm ${
                  run.status === "completed" ? "bg-green-100 text-green-800" :
                  run.status === "started" ? "bg-yellow-100 text-yellow-800" :
                  "bg-gray-100 text-gray-800"
                }`}>
                  {run.status}
                </span>
              </td>
              <td className="border p-3 text-right">{run.variances_count}</td>
              <td className="border p-3 text-right">
                <span className={`font-bold ${run.material_count > 0 ? "text-red-600" : "text-green-600"}`}>
                  {run.material_count}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
