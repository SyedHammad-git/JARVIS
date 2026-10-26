import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Documentation" };

export default function DocsPage() {
  return (
    <main className="site-width section-block">
      <p className="section-kicker">JARVIS DOCUMENTATION</p>
      <h1 className="mt-3 text-4xl font-bold tracking-tight">Get started</h1>
      <p className="muted mt-4 max-w-2xl leading-7">Guides for pairing your Windows desktop app, configuring your own AI provider key, and using the dashboard.</p>
      <div className="mt-8 grid gap-4 md:grid-cols-2">
        <Link href="/docs/connect" className="panel block p-6 no-underline">
          <h2 className="text-lg font-bold text-[var(--ink)]">Connect your devices</h2>
          <p className="muted mt-2 leading-7">Pair your Windows client with your dashboard using a one-time code.</p>
        </Link>
        <Link href="/docs/api-keys" className="panel block p-6 no-underline">
          <h2 className="text-lg font-bold text-[var(--ink)]">Configure an AI provider</h2>
          <p className="muted mt-2 leading-7">Add a provider key to your account to start chatting.</p>
        </Link>
      </div>
    </main>
  );
}
