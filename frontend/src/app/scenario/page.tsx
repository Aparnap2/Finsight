import { ScenarioCard } from "@/components/ScenarioCard";

export default function ScenarioPage() {
  const scenarios = [
    {
      name: "Base Case",
      description: "Current trajectory with identified root causes addressed",
      revenue_impact: 0,
      ebitda_impact: 0,
      cash_impact: 0,
      probability_assessment: "high",
    },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Scenario Explorer</h1>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {scenarios.map((s) => (
          <ScenarioCard key={s.name} scenario={s} />
        ))}
      </div>
    </div>
  );
}
