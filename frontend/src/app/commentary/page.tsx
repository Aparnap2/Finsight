"use client";

import { useEffect, useState } from "react";
import { CommentaryEditor } from "@/components/CommentaryEditor";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function CommentaryPage() {
  const [sections, setSections] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [runId, setRunId] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/pipeline/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ period: "2026-06", entity_id: "CF001", run_sync: true }),
    })
      .then((r) => r.json())
      .then((data) => {
        setRunId(data.run_id);
        setSections(data.commentary_sections || []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const handleReview = async (decision: string) => {
    if (!runId) return;
    await fetch(
      `${API_BASE}/api/v1/pipeline/${runId}/review?checkpoint=commentary&decision=${decision}`,
      { method: "POST" }
    );
    alert(`Commentary ${decision}d`);
  };

  if (loading) return <div className="p-8">Loading commentary...</div>;

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Commentary Editor</h1>
      <p className="text-gray-500 mb-4">
        {sections.length} sections generated for period 2026-06
      </p>
      <CommentaryEditor sections={sections} />
      <div className="mt-6 flex gap-4">
        <button
          onClick={() => handleReview("approve")}
          className="px-6 py-2 bg-green-600 text-white rounded hover:bg-green-700"
        >
          Approve
        </button>
        <button
          onClick={() => handleReview("reject")}
          className="px-6 py-2 bg-red-600 text-white rounded hover:bg-red-700"
        >
          Reject
        </button>
      </div>
    </div>
  );
}
