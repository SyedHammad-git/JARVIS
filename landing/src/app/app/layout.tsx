import Link from "next/link";
import { UserButton } from "@clerk/nextjs";

export default function DashboardLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="site-width min-h-screen pb-12">
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-[var(--line)] py-5">
        <Link href="/app" className="text-sm font-bold tracking-[0.2em] text-[var(--ink)] no-underline">J.A.R.V.I.S.</Link>
        <nav aria-label="Dashboard navigation" className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
          <Link href="/app">Chat</Link>
          <Link href="/app/devices">Devices</Link>
          <Link href="/app/settings/keys">API keys</Link>
          <UserButton />
        </nav>
      </header>
      {children}
    </div>
  );
}
