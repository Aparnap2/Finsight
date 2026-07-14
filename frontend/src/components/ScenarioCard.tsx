interface Scenario {
  name: string;
  description: string;
  revenue_impact: number;
  ebitda_impact: number;
  cash_impact: number;
  probability_assessment: string;
}

export function ScenarioCard({ scenario }: { scenario: Scenario }) {
  return (
    <div className="border rounded-lg p-6 shadow-sm bg-white">
      <h3 className="text-lg font-semibold mb-2">{scenario.name}</h3>
      <p className="text-gray-600 mb-4">{scenario.description}</p>
      <table className="w-full text-sm">
        <tbody>
          <tr>
            <td className="py-1">Revenue Impact</td>
            <td className="text-right">
              ${scenario.revenue_impact.toLocaleString()}
            </td>
          </tr>
          <tr>
            <td className="py-1">EBITDA Impact</td>
            <td className="text-right">
              ${scenario.ebitda_impact.toLocaleString()}
            </td>
          </tr>
          <tr>
            <td className="py-1">Cash Impact</td>
            <td className="text-right">
              ${scenario.cash_impact.toLocaleString()}
            </td>
          </tr>
          <tr>
            <td className="py-1">Probability</td>
            <td className="text-right">{scenario.probability_assessment}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
