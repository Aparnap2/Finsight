"use client";

import { useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function DashboardPage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/pipeline/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ period: "2026-06", entity_id: "CF001", run_sync: true }),
    })
      .then((r) => r.json())
      .then((d) => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-8">Loading...</div>;

  const material = data?.material_count || 0;

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">FinSight Dashboard</h1>
      <div className="mt-8 grid grid-cols-1 md:grid-cols-4 gap-6">
        <div className="bg-white p-6 rounded-lg shadow">
          <h2 className="font-semibold text-gray-700">Pipeline Status</h2>
          <p className="text-3xl font-bold text-green-600 mt-2">
            {data?.status || "Ready"}
          </p>
        </div>
        <div className="bg-white p-6 rounded-lg shadow">
          <h2 className="font-semibold text-gray-700">Period</h2>
          <p className="text-3xl font-bold text-blue-600 mt-2">
            {data?.period || "—"}
          </p>
        </div>
        <div className="bg-white p-6 rounded-lg shadow">
          <h2 className="font-semibold text-gray-700">Total Variances</h2>
          <p className="text-3xl font-bold text-orange-600 mt-2">
            {data?.variances?.length || 0}
          </p>
        </div>
        <div className="bg-white p-6 rounded-lg shadow">
          <h2 className="font-semibold text-gray-700">Material Variances</h2>
          <p className="text-3xl font-bold text-red-600 mt-2">{material}</p>
        </div>
      </div>
      {data?.root_causes && data.root_causes.length > 0 && (
        <div className="mt-8 bg-white p-6 rounded-lg shadow">
          <h2 className="font-semibold text-gray-700 mb-4">Root-Cause Findings</h2>
          {data.root_causes.map((rc: any, i: number) => (
            <div key={i} className="border-l-4 border-blue-500 pl-4 mb-3">
              <p className="font-medium">{rc.summary}</p>
              <p className="text-sm text-gray-500">
                Confidence: {(rc.confidence_score * 100).toFixed(0)}% — {rc.recommended_action}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
