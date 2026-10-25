"use client";

import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { ApiError, apiFetch } from "@/lib/api";

type Device = { device_id: string; name: string; online: boolean; revoked: number };
type AgentReply = {
  ok: boolean;
  reply?: string;
  model?: string;
  error?: string;
  needs_confirmation?: boolean;
  confirmation_nonce?: string;
  confirmation_expires_in?: number;
  reason?: string;
};
type PendingConfirmation = { message: string; nonce: string; reason?: string };

export default function DashboardPage() {
  const { getToken } = useAuth();
  const [message, setMessage] = useState("");
  const [reply, setReply] = useState("");
  const [deviceState, setDeviceState] = useState<"loading" | "online" | "offline" | "error">("loading");
  const [pending, setPending] = useState(false);
  const [confirmation, setConfirmation] = useState<PendingConfirmation | null>(null);
  const [error, setError] = useState("");
  const [needsKey, setNeedsKey] = useState(false);

  const refreshDeviceStatus = useCallback(async () => {
    try {
      const result = await apiFetch<{ devices: Device[] }>(getToken, "/api/devices");
      setDeviceState(result.devices.some((device) => device.online && !device.revoked) ? "online" : "offline");
    } catch (cause) {
      setDeviceState("error");
      if (cause instanceof ApiError && cause.code === "authentication_required") setError(cause.message);
      else if (cause instanceof ApiError && cause.code === "offline") setError("Backend unavailable. Check your connection.");
    }
  }, [getToken]);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => void refreshDeviceStatus(), 0);
    const timer = window.setInterval(() => void refreshDeviceStatus(), 30_000);
    return () => {
      window.clearTimeout(initialLoad);
      window.clearInterval(timer);
    };
  }, [refreshDeviceStatus]);

  async function sendRequest(text: string, confirmed = false, nonce?: string) {
    if (!text.trim() || pending) return;
    setPending(true);
    setError("");
    setNeedsKey(false);
    try {
      const result = await apiFetch<AgentReply>(getToken, "/api/agent", {
        method: "POST",
        body: { message: text, confirmed, confirmation_nonce: nonce },
      });
      setReply(result.reply || "No response was returned.");
      if (result.needs_confirmation && result.confirmation_nonce) {
        setConfirmation({ message: text, nonce: result.confirmation_nonce, reason: result.reason });
      } else {
        setConfirmation(null);
        setMessage("");
      }
    } catch (cause) {
      setConfirmation(null);
      if (cause instanceof ApiError && cause.code === "no_api_key") setNeedsKey(true);
      else setError(cause instanceof Error ? cause.message : "The request failed. Please try again.");
    } finally {
      setPending(false);
    }
  }

  function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (confirmation) return;
    void sendRequest(message.trim());
  }

  return (
    <main className="mx-auto max-w-3xl py-8 md:py-12">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.22em] text-[var(--accent)]">Private dashboard</p>
          <h1 className="mt-2 text-3xl font-bold">JARVIS chat</h1>
        </div>
        <div className="panel flex items-center gap-2 px-3 py-2 text-sm" role="status" aria-live="polite">
          <span aria-hidden="true" className={`h-2.5 w-2.5 rounded-full ${deviceState === "online" ? "bg-emerald-400" : deviceState === "offline" || deviceState === "error" ? "bg-rose-400" : "animate-pulse bg-amber-300"}`} />
          <span>{deviceState === "loading" ? "Checking device" : deviceState === "error" ? "Backend unavailable" : deviceState === "online" ? "Device online" : "Device offline"}</span>
        </div>
      </div>
      {needsKey && (
        <aside className="panel mt-6 border-amber-500/60 p-4" role="alert">
          <h2 className="font-bold">Add an AI provider key to begin</h2>
          <p className="muted mt-1">The backend has no configured AI provider key for this account.</p>
          <Link className="mt-3 inline-block" href="/app/settings/keys">Add an API key →</Link>
        </aside>
      )}
      {error && <p className="mt-5 rounded-lg border border-rose-500/50 p-3 text-sm" role="alert">{error}</p>}
      {confirmation && (
        <aside className="panel mt-6 border-amber-500/60 p-4" role="alert">
          <h2 className="font-bold">Confirm this action</h2>
          <p className="muted mt-1">{confirmation.reason || "JARVIS needs your approval before continuing."} This request expires in about one minute.</p>
          <button
            className="button-primary mt-3"
            type="button"
            disabled={pending}
            onClick={() => void sendRequest(confirmation.message, true, confirmation.nonce)}
          >
            {pending ? "Working…" : "Confirm action"}
          </button>
          <button className="button-secondary ml-2 mt-3" type="button" disabled={pending} onClick={() => setConfirmation(null)}>Cancel</button>
        </aside>
      )}
      <section className="panel mt-7 p-4 md:p-6" aria-label="Chat with JARVIS">
        <div className="min-h-48 rounded-lg bg-[var(--panel-raised)] p-4" aria-live="polite" aria-label="Assistant response">
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--accent)]">JARVIS</p>
          <p className="mt-3 whitespace-pre-wrap leading-7">{reply || "Ready when you are. Your PC must be on and the JARVIS desktop app running for device actions."}</p>
        </div>
        <form className="mt-4" onSubmit={sendMessage}>
          <label htmlFor="chat-message" className="mb-2 block text-sm font-semibold">Your message</label>
          <textarea id="chat-message" className="field min-h-28 resize-y" value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Ask JARVIS something…" required />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <p className="muted text-xs">Camera access is never automatic; the desktop app requires your approval.</p>
            <button className="button-primary" type="submit" disabled={pending || !message.trim() || confirmation !== null}>{pending ? "Sending…" : "Send message"}</button>
          </div>
        </form>
      </section>
      <div className="muted mt-5 flex flex-wrap gap-4 text-sm">
        <Link href="/app/devices">Manage paired devices</Link>
        <Link href="/app/settings/keys">Manage provider keys</Link>
        <Link href="/docs/connect">Connection help</Link>
      </div>
    </main>
  );
}
