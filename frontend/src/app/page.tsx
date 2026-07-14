export default function DashboardPage() {
  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">FinSight Dashboard</h1>
      <p className="text-gray-600">Welcome to the FP&A Operations Platform</p>
      <div className="mt-8 grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-white p-6 rounded-lg shadow">
          <h2 className="font-semibold text-gray-700">Pipeline Status</h2>
          <p className="text-3xl font-bold text-green-600 mt-2">Ready</p>
        </div>
        <div className="bg-white p-6 rounded-lg shadow">
          <h2 className="font-semibold text-gray-700">Last Run</h2>
          <p className="text-3xl font-bold text-blue-600 mt-2">2026-06</p>
        </div>
        <div className="bg-white p-6 rounded-lg shadow">
          <h2 className="font-semibold text-gray-700">Material Variances</h2>
          <p className="text-3xl font-bold text-red-600 mt-2">2</p>
        </div>
      </div>
    </div>
  );
}
