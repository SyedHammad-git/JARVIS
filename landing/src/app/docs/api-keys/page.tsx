import type { Metadata } from "next";
import Link from "next/link";
import { PROVIDERS } from "@/lib/providers";

export const metadata: Metadata = { title: "Get an AI provider key" };

export default function ApiKeyGuidePage() {
  return (
    <main className="site-width max-w-4xl py-10 md:py-16">
      <Link href="/" className="text-sm">← Home</Link>
      <p className="mt-8 text-xs font-bold uppercase tracking-[0.25em] text-[var(--accent)]">Key setup</p>
      <h1 className="mt-3 text-4xl font-bold">Bring your own provider key</h1>
      <p className="muted mt-4 leading-7">Create a key with the provider, then paste it into <Link href="/app/settings/keys">Dashboard → API keys</Link>. Keys are encrypted at rest by the backend. The dashboard shows only the provider status and last four characters.</p>
      <div className="mt-8 space-y-4">
        {PROVIDERS.map((provider) => (
          <section className="panel p-5" key={provider.id}>
            <h2 className="text-xl font-bold">{provider.name}{provider.optional ? " (optional)" : ""}</h2>
            <ol className="muted mt-3 list-decimal space-y-2 pl-5 leading-6">
              {provider.steps.map((step) => <li key={step}>{step}</li>)}
            </ol>
            <a href={provider.url} target="_blank" rel="noreferrer" className="mt-4 inline-block">Open {provider.name} key settings ↗</a>
          </section>
        ))}
      </div>
      <p className="muted mt-7 leading-7"><strong className="text-[var(--ink)]">Free-tier caveat:</strong> Providers may offer free usage, but limits, eligibility, and pricing change. Check each provider’s page for current terms and quotas before use.</p>
    </main>
  );
}
