import { CommentaryEditor } from "@/components/CommentaryEditor";

export default function CommentaryPage() {
  const sections = [
    { section_type: "executive_summary", content: "June results analysis pending..." },
    { section_type: "revenue", content: "Revenue commentary pending..." },
    { section_type: "cost", content: "Cost commentary pending..." },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Commentary Editor</h1>
      <CommentaryEditor sections={sections} />
    </div>
  );
}
