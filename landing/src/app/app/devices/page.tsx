"use client";

import { useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Device = {
  device_id: string;
  name: string;
  online: boolean;
  revoked: number;
  last_seen: string;
};

type PairCode = { code: string; expires_at: number };
const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL;

function remainingTime(expiresAt: number, now: number): string {
  const seconds = Math.max(0, Math.ceil(expiresAt - now));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export default function DevicesPage() {
  const { getToken } = useAuth();
  const [devices, setDevices] = useState<Device[]>([]);
  const [pairCode, setPairCode] = useState<PairCode | null>(null);
  const [now, setNow] = useState(() => Date.now() / 1000);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [copied, setCopied] = useState(false);

  const loadDevices = useCallback(async () => {
    setError("");
    try {
      const result = await apiFetch<{ devices: Device[] }>(getToken, "/api/devices");
      setDevices(result.devices.filter((device) => !device.revoked));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load devices.");
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => void loadDevices(), 0);
    return () => window.clearTimeout(initialLoad);
  }, [loadDevices]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, []);

  async function createCode() {
    setBusy(true);
    setError("");
    setNotice("");
    setCopied(false);
    try {
      const result = await apiFetch<PairCode>(getToken, "/api/devices/pair-code", {
        method: "POST",
        body: { name: "PC" },
      });
      setPairCode(result);
      setNotice("Code created. Enter it in the JARVIS desktop app within 10 minutes.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create a pairing code.");
    } finally {
      setBusy(false);
    }
  }

  async function copyCode() {
    if (!pairCode) return;
    try {
      await navigator.clipboard.writeText(pairCode.code);
      setCopied(true);
      setError("");
    } catch {
      setCopied(false);
      setError("Clipboard access is unavailable. Select and copy the code manually.");
    }
  }

  async function revoke(deviceId: string) {
    setBusy(true);
    setError("");
    try {
      await apiFetch(getToken, `/api/devices/${encodeURIComponent(deviceId)}/revoke`, { method: "POST" });
      setNotice("Device access revoked.");
      await loadDevices();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not revoke this device.");
    } finally {
      setBusy(false);
    }
  }

  const codeExpired = pairCode !== null && pairCode.expires_at <= now;
  return (
    <main className="mx-auto max-w-3xl py-8 md:py-12">
      <p className="text-xs font-bold uppercase tracking-[0.22em] text-[var(--accent)]">Settings</p>
      <h1 className="mt-2 text-3xl font-bold">Devices</h1>
      <p className="muted mt-3 leading-7">Install the desktop app on the PC you want to connect, then enter a one-time code below. Your PC must be on with the JARVIS app running.</p>
      {error && <p className="mt-5 rounded-lg border border-rose-500/50 p-3 text-sm" role="alert">{error}</p>}
      {notice && <p className="mt-5 rounded-lg border border-emerald-500/50 p-3 text-sm" role="status">{notice}</p>}
      <section className="panel mt-6 p-5" aria-labelledby="pair-heading">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div><h2 id="pair-heading" className="text-xl font-bold">Add device</h2><p className="muted mt-1 text-sm">Codes are single-use and expire after 10 minutes.</p></div>
          <button className="button-primary" type="button" onClick={() => void createCode()} disabled={busy}>{busy ? "Please wait…" : "Create pairing code"}</button>
        </div>
        {pairCode && (
          <div className="mt-5 rounded-lg border border-[var(--line)] bg-[var(--panel-raised)] p-4" aria-live="polite">
            {codeExpired ? (
              <p className="font-semibold" role="status">This code expired. Create a new code to continue.</p>
            ) : (
              <>
                <p className="muted text-sm">Enter this code in the desktop app · Expires in {remainingTime(pairCode.expires_at, now)}</p>
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <output className="font-mono text-3xl font-bold tracking-[0.22em]" aria-label="Pairing code">{pairCode.code}</output>
                  <button className="button-secondary" type="button" onClick={() => void copyCode()}>{copied ? "Copied" : "Copy code"}</button>
                </div>
              </>
            )}
          </div>
        )}
        <p className="muted mt-4 text-sm">
          Install the desktop app, open Pair this PC, enter the backend URL{" "}
          {backendUrl ? <code className="break-all">{backendUrl}</code> : "provided by your administrator"}{" "}
          and this code.
        </p>
      </section>
      <section className="mt-9" aria-labelledby="devices-heading">
        <h2 id="devices-heading" className="text-xl font-bold">Paired devices</h2>
        {loading ? <p className="muted mt-4" role="status">Loading devices…</p> : devices.length === 0 ? (
          <p className="muted mt-4">No devices paired yet.</p>
        ) : (
          <ul className="mt-4 space-y-3 p-0">
            {devices.map((device) => (
              <li key={device.device_id} className="panel flex flex-wrap items-center justify-between gap-4 p-4">
                <div>
                  <h3 className="font-bold">{device.name}</h3>
                  <p className={`mt-1 text-sm ${device.online ? "status-online" : "status-offline"}`}>{device.online ? "Online" : "Offline"}</p>
                  <p className="muted mt-1 text-xs">Last seen: {device.last_seen || "Not connected yet"}</p>
                </div>
                <button className="button-secondary" type="button" disabled={busy} onClick={() => void revoke(device.device_id)}>Revoke</button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
