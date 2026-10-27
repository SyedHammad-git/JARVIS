import type { Metadata } from "next";
import Link from "next/link";
import { getDownloadRelease } from "@/lib/download";

export const metadata: Metadata = { title: "Download for Windows" };

export default function DownloadPage() {
  const release = getDownloadRelease(
    process.env.NEXT_PUBLIC_DOWNLOAD_URL,
    process.env.NEXT_PUBLIC_DOWNLOAD_VERSION,
    process.env.NEXT_PUBLIC_DOWNLOAD_SHA256,
  );

  return (
    <main className="site-width py-10 md:py-16">
      <Link href="/" className="text-sm">← Home</Link>
      <div className="mt-8 max-w-3xl">
        <p className="text-xs font-bold uppercase tracking-[0.25em] text-[var(--accent)]">Windows desktop client</p>
        <h1 className="mt-3 text-4xl font-bold">Download J.A.R.V.I.S.</h1>
        <p className="muted mt-4 leading-7">Install the desktop app on the PC you want to connect. It must be powered on and running while you use remote features.</p>
        <div className="panel mt-8 p-6">
          <div className="flex flex-wrap justify-between gap-3">
            <div><p className="muted text-sm">Latest release</p><p className="mt-1 text-xl font-semibold">{release.version ? `Version ${release.version}` : "Version not published"}</p></div>
            {release.url ? (
              <a className="button-primary self-center" href={release.url} target="_blank" rel="noreferrer">Download installer</a>
            ) : (
              <button className="button-primary self-center opacity-60" type="button" disabled>Coming soon</button>
            )}
          </div>
          {release.invalidUrl && <p className="mt-4 text-sm text-rose-500" role="alert">The configured download must be an HTTPS GitHub Release asset URL.</p>}
          {release.invalidChecksum && <p className="mt-4 text-sm text-rose-500" role="alert">The configured checksum must contain exactly 64 hexadecimal characters.</p>}
          <div className="mt-6 border-t border-[var(--line)] pt-5">
            <h2 className="font-bold">SHA-256 checksum</h2>
            <p className="mt-2 break-all font-mono text-sm" aria-label="SHA-256 checksum">{release.sha256 || "Checksum not published yet."}</p>
          </div>
        </div>
        <h2 className="mt-10 text-xl font-bold">Install and pair</h2>
        <ol className="muted mt-4 space-y-3 pl-6 leading-7">
          <li>Download and run the installer on Windows.</li>
          <li>Open the app and leave it running in the notification area.</li>
          <li>Sign in on your phone or browser, open <Link href="/app/devices">Devices</Link>, and create a pairing code.</li>
          <li>Enter the code in the desktop app. It expires after 10 minutes and can be used once.</li>
        </ol>
        <aside className="panel mt-8 border-amber-500/60 p-5" aria-labelledby="smartscreen-heading">
          <h2 id="smartscreen-heading" className="font-bold">Windows SmartScreen note</h2>
          <p className="muted mt-2 leading-7">Unsigned builds may show a Microsoft Defender SmartScreen warning. Only continue if you downloaded the installer from the official release link above and verified the SHA-256 checksum. In the warning, select <strong className="text-[var(--ink)]">More info</strong>, confirm the publisher information is unavailable, then choose <strong className="text-[var(--ink)]">Run anyway</strong>. If the checksum does not match or you are unsure, cancel the install.</p>
        </aside>
        <p className="mt-7">First time setting up? Read the <Link href="/docs/connect">device pairing guide</Link>.</p>
      </div>
    </main>
  );
}
