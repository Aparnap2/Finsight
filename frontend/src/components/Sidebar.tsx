"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const navItems = [
  { href: "/", label: "Dashboard" },
  { href: "/variance", label: "Variance Heatmap" },
  { href: "/commentary", label: "Commentary" },
  { href: "/scenario", label: "Scenarios" },
  { href: "/runs", label: "Agent Runs" },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="w-64 bg-gray-900 text-white p-4 min-h-screen">
      <h1 className="text-xl font-bold mb-8">FinSight</h1>
      <nav className="space-y-2">
        {navItems.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={`block px-3 py-2 rounded ${
              pathname === item.href ? "bg-gray-700" : "hover:bg-gray-800"
            }`}
          >
            {item.label}
          </Link>
        ))}
      </nav>
    </aside>
  );
}
