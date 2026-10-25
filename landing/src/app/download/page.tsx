import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Download for Windows" };

function releaseAssetUrl(value: string | undefined): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname === "github.com" && /\/releases\/download\/[^/]+\/[^/]+$/.test(url.pathname)
      ? url.toString()
      : undefined;
  } catch {
    return undefined;
  }
}

const configuredDownloadUrl = process.env.NEXT_PUBLIC_DOWNLOAD_URL;
const downloadUrl = releaseAssetUrl(configuredDownloadUrl);
const checksum = process.env.NEXT_PUBLIC_DOWNLOAD_SHA256;

export default function DownloadPage() {
  return (
    <main className="site-width py-10 md:py-16">
      <Link href="/" className="text-sm">← Home</Link>
      <div className="mt-8 max-w-3xl">
        <p className="text-xs font-bold uppercase tracking-[0.25em] text-[var(--accent)]">Windows desktop client</p>
        <h1 className="mt-3 text-4xl font-bold">Download J.A.R.V.I.S.</h1>
        <p className="muted mt-4 leading-7">Install the desktop app on the PC you want to connect. It must be powered on and running while you use remote features.</p>
        <div className="panel mt-8 p-6">
          <div className="flex flex-wrap justify-between gap-3">
            <div><p className="muted text-sm">Latest release</p><p className="mt-1 text-xl font-semibold">Version 18.0.0</p></div>
            <Link className="button-primary self-center" href={downloadUrl || "/docs/connect"} target={downloadUrl ? "_blank" : undefined} rel={downloadUrl ? "noreferrer" : undefined}>
              {downloadUrl ? "Download installer" : "Download unavailable"}
            </Link>
          </div>
          {configuredDownloadUrl && !downloadUrl && <p className="mt-4 text-sm text-rose-500" role="alert">The configured download must be an HTTPS GitHub Release asset URL.</p>}
          <div className="mt-6 border-t border-[var(--line)] pt-5">
            <h2 className="font-bold">SHA-256 checksum</h2>
            <p className="mt-2 break-all font-mono text-sm" aria-label="SHA-256 checksum">{checksum || "Checksum not published yet."}</p>
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
          <p className="muted mt-2 leading-7">This installer is currently unsigned, so Windows may show a Microsoft Defender SmartScreen warning. Only continue if you downloaded the installer from the official release link above and have verified the SHA-256 checksum. In the warning, select <strong className="text-[var(--ink)]">More info</strong>, confirm the publisher information is unavailable, then choose <strong className="text-[var(--ink)]">Run anyway</strong>. If the checksum does not match or you are unsure, cancel the install.</p>
        </aside>
        <p className="mt-7">First time setting up? Read the <Link href="/docs/connect">device pairing guide</Link>.</p>
      </div>
    </main>
  );
}
