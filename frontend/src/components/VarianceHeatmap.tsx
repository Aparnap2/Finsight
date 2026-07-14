"use client";

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

export function VarianceHeatmap({ variances }: { variances: Variance[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full border-collapse">
        <thead>
          <tr className="bg-gray-100">
            <th className="border p-2 text-left">Account</th>
            <th className="border p-2 text-left">Department</th>
            <th className="border p-2 text-right">Actual</th>
            <th className="border p-2 text-right">Budget</th>
            <th className="border p-2 text-right">Variance</th>
            <th className="border p-2 text-right">%</th>
            <th className="border p-2 text-center">Material</th>
          </tr>
        </thead>
        <tbody>
          {variances.map((v) => (
            <tr key={v.account_id} className={v.is_material ? "bg-red-50" : ""}>
              <td className="border p-2">{v.account_name}</td>
              <td className="border p-2">{v.department}</td>
              <td className="border p-2 text-right">${v.actual_amount.toLocaleString()}</td>
              <td className="border p-2 text-right">${v.budget_amount.toLocaleString()}</td>
              <td className="border p-2 text-right">${v.variance_amount.toLocaleString()}</td>
              <td className="border p-2 text-right">{v.variance_pct.toFixed(1)}%</td>
              <td className="border p-2 text-center">
                {v.is_material && <span className="text-red-600 font-bold">!</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
