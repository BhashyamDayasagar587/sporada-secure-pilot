import { ReactNode, useState } from "react";
import { NavLink } from "react-router-dom";
import { Gauge, Video, Terminal, SlidersHorizontal, Menu } from "lucide-react";
import { useLightTheme } from "../lib/theme";
import { useAnalyticsStream } from "../lib/ws";

const NAV = [
  { to: "/monitor", label: "Monitor", icon: Gauge },
  { to: "/live", label: "Live", icon: Video },
  { to: "/stream", label: "Stream", icon: Terminal },
  { to: "/config", label: "Config", icon: SlidersHorizontal },
];

export default function Layout({ children }: { children: ReactNode }) {
  useLightTheme();
  const [collapsed, setCollapsed] = useState(false);
  const connected = useAnalyticsStream(() => {});
  return (
    <div className="flex h-full">
      <aside
        className={`shrink-0 bg-rail text-slate-300 transition-all duration-150 ${
          collapsed ? "w-14" : "w-56"
        }`}
      >
        <div className="flex items-center gap-2 px-3 h-14 border-b border-white/10">
          <button
            className="p-2 rounded hover:bg-white/10 text-slate-300"
            onClick={() => setCollapsed((value) => !value)}
            aria-label="Toggle sidebar"
          >
            <Menu className="w-4 h-4" />
          </button>
          {!collapsed && (
            <span className="font-bold text-sm tracking-[0.2em] text-white">TRAFFIC</span>
          )}
        </div>
        <nav className="flex flex-col gap-0.5 p-2">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-3 py-2 pr-3 pl-[9px] rounded text-sm border-l-[3px] transition-colors ${
                  isActive
                    ? "border-ok-400 bg-brand-600 text-white font-medium"
                    : "border-transparent text-slate-300 hover:bg-white/10 hover:text-white"
                }`
              }
            >
              <Icon className="w-4 h-4 shrink-0" />
              {!collapsed && <span>{label}</span>}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="flex-1 flex flex-col min-w-0 bg-canvas">
        <header className="h-14 px-4 flex items-center justify-between border-b border-slate-200 bg-panel">
          <div className="flex items-center gap-3">
            <span
              className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-medium ${
                connected ? "bg-ok-100 text-ok-700" : "bg-crit-100 text-crit-700"
              }`}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${connected ? "bg-ok-500" : "bg-crit-500"}`} />
              {connected ? "Live" : "Offline"}
            </span>
            <span className="text-xs text-slate-500">{new Date().toLocaleString()}</span>
          </div>
        </header>
        <div className="flex-1 overflow-auto p-6">{children}</div>
      </main>
    </div>
  );
}
