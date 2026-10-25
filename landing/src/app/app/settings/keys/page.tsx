"use client";

import { useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useState } from "react";
import { ApiError, apiFetch } from "@/lib/api";
import { PROVIDERS, ProviderId } from "@/lib/providers";

type ProviderStatus = { provider: ProviderId; configured: boolean; last4: string };

export default function KeySettingsPage() {
  const { getToken } = useAuth();
  const [statuses, setStatuses] = useState<ProviderStatus[]>([]);
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const loadStatuses = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await apiFetch<{ providers: ProviderStatus[] }>(getToken, "/api/keys");
      setStatuses(response.providers);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load key status.");
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => void loadStatuses(), 0);
    return () => window.clearTimeout(initialLoad);
  }, [loadStatuses]);

  async function save(provider: ProviderId) {
    const key = keys[provider] || "";
    if (!key.trim()) {
      setError("Paste a key before saving.");
      return;
    }
    setBusy(provider);
    setError("");
    setNotice("");
    try {
      await apiFetch(getToken, `/api/keys/${provider}`, { method: "POST", body: { key } });
      setKeys((current) => ({ ...current, [provider]: "" }));
      setNotice(`${PROVIDERS.find((item) => item.id === provider)?.name} key saved securely.`);
      await loadStatuses();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save this key.");
    } finally {
      setBusy(null);
    }
  }

  async function test(provider: ProviderId) {
    const key = keys[provider] || "";
    if (!key.trim()) {
      setError("Paste a key to test it. The test does not save the key.");
      return;
    }
    setBusy(provider);
    setError("");
    setNotice("");
    try {
      const result = await apiFetch<{ valid: boolean }>(getToken, `/api/keys/${provider}/test`, {
        method: "POST",
        body: { key },
      });
      setNotice(result.valid ? "Key verified with the provider." : "The provider rejected this key.");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not test this key.");
    } finally {
      setBusy(null);
    }
  }

  async function remove(provider: ProviderId) {
    setBusy(provider);
    setError("");
    setNotice("");
    try {
      await apiFetch(getToken, `/api/keys/${provider}`, { method: "DELETE" });
      setNotice(`${PROVIDERS.find((item) => item.id === provider)?.name} key deleted.`);
      await loadStatuses();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not delete this key.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="mx-auto max-w-3xl py-8 md:py-12">
      <p className="text-xs font-bold uppercase tracking-[0.22em] text-[var(--accent)]">Settings</p>
      <h1 className="mt-2 text-3xl font-bold">API keys</h1>
      <p className="muted mt-3 max-w-2xl leading-7">Keys are sent directly to your authenticated backend over HTTPS and encrypted before storage. Only status and the final four characters are returned. Key fields are never written to browser storage and clear after saving.</p>
      {loading && <p className="muted mt-6" role="status">Loading provider status…</p>}
      {error && <p className="mt-5 rounded-lg border border-rose-500/50 p-3 text-sm" role="alert">{error}</p>}
      {notice && <p className="mt-5 rounded-lg border border-emerald-500/50 p-3 text-sm" role="status">{notice}</p>}
      <div className="mt-7 space-y-4">
        {PROVIDERS.map((provider) => {
          const status = statuses.find((item) => item.provider === provider.id);
          return (
            <section className="panel p-5" key={provider.id} aria-labelledby={`${provider.id}-heading`}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 id={`${provider.id}-heading`} className="text-xl font-bold">{provider.name}{provider.optional ? " (optional)" : ""}</h2>
                  <p className="muted mt-1 text-sm">Status: {loading ? "Loading…" : status?.configured ? `Configured · •••• ${status.last4}` : "Not configured"}</p>
                </div>
                <a href={provider.url} target="_blank" rel="noreferrer" className="text-sm">Where do I get this key?</a>
              </div>
              <ol className="muted mt-4 list-decimal space-y-1 pl-5 text-sm leading-6">
                {provider.steps.map((step) => <li key={step}>{step}</li>)}
              </ol>
              <label htmlFor={`${provider.id}-key`} className="mt-5 block text-sm font-semibold">Paste {provider.name} key</label>
              <input
                id={`${provider.id}-key`}
                className="field mt-2"
                type="password"
                autoComplete="new-password"
                spellCheck={false}
                value={keys[provider.id] || ""}
                onChange={(event) => setKeys((current) => ({ ...current, [provider.id]: event.target.value }))}
              />
              <div className="mt-3 flex flex-wrap gap-2">
                <button className="button-primary" type="button" disabled={busy === provider.id || loading} onClick={() => void save(provider.id)}>{busy === provider.id ? "Working…" : "Save key"}</button>
                <button className="button-secondary" type="button" disabled={busy === provider.id || loading} onClick={() => void test(provider.id)}>Test key</button>
                <button className="button-secondary" type="button" disabled={busy === provider.id || loading || !status?.configured} onClick={() => void remove(provider.id)}>Delete key</button>
              </div>
            </section>
          );
        })}
      </div>
    </main>
  );
}
