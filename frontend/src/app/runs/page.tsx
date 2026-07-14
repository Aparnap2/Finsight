export default function RunsPage() {
  const steps = [
    { name: "Ingestion", status: "completed" },
    { name: "Variance Detection", status: "completed" },
    { name: "Root Cause", status: "pending" },
    { name: "Commentary", status: "pending" },
    { name: "Scenario", status: "pending" },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Agent Run Timeline</h1>
      <div className="flex items-center space-x-4">
        {steps.map((step, i) => (
          <div key={step.name} className="flex items-center">
            <div
              className={`px-4 py-2 rounded ${
                step.status === "completed"
                  ? "bg-green-100 text-green-800"
                  : "bg-gray-100 text-gray-500"
              }`}
            >
              {step.name}
            </div>
            {i < steps.length - 1 && (
              <div className="w-8 h-0.5 bg-gray-300 mx-2" />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
