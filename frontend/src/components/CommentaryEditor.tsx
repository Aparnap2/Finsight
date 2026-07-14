"use client";
import { useState } from "react";

interface Section {
  section_type: string;
  content: string;
}

export function CommentaryEditor({ sections }: { sections: Section[] }) {
  const [draft, setDraft] = useState(sections);

  return (
    <div className="space-y-4">
      {draft.map((s, i) => (
        <div key={s.section_type} className="border rounded p-4">
          <h3 className="font-semibold mb-2 capitalize">
            {s.section_type.replace("_", " ")}
          </h3>
          <textarea
            className="w-full border rounded p-2 min-h-[100px]"
            value={s.content}
            onChange={(e) => {
              const updated = [...draft];
              updated[i] = { ...updated[i], content: e.target.value };
              setDraft(updated);
            }}
          />
        </div>
      ))}
    </div>
  );
}
