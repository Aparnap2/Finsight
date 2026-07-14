import { VarianceHeatmap } from "@/components/VarianceHeatmap";

export default function VariancePage() {
  const mockVariances = [
    {
      account_id: "4001",
      account_name: "Revenue - Product Y",
      department: "Sales",
      actual_amount: 100000,
      budget_amount: 120000,
      variance_amount: -20000,
      variance_pct: -16.7,
      is_material: true,
    },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Variance Heatmap</h1>
      <VarianceHeatmap variances={mockVariances} />
    </div>
  );
}
