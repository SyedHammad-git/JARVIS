import Link from "next/link";
import { UserButton } from "@clerk/nextjs";
import { ThemeToggle } from "@/components/ThemeToggle";

export default function DashboardLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="site-width min-h-screen pb-12">
      <header className="dashboard-header">
        <Link href="/app" className="brand-lockup"><span className="brand-mark" aria-hidden="true">J</span><span>J.A.R.V.I.S.</span></Link>
        <nav aria-label="Dashboard navigation" className="dashboard-nav">
          <Link href="/app">Chat</Link>
          <Link href="/app/devices">Devices</Link>
          <Link href="/app/settings/keys">API keys</Link>
          <ThemeToggle />
          <UserButton />
        </nav>
      </header>
      {children}
    </div>
  );
}
