import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Connect your devices" };

export default function ConnectGuidePage() {
  return (
    <main className="site-width max-w-4xl py-10 md:py-16">
      <Link href="/" className="text-sm">← Home</Link>
      <p className="mt-8 text-xs font-bold uppercase tracking-[0.25em] text-[var(--accent)]">Setup guide</p>
      <h1 className="mt-3 text-4xl font-bold">Connect your phone and PC</h1>
      <p className="muted mt-4 max-w-2xl leading-7">The phone talks to the backend over HTTPS. The Windows app keeps a secure outgoing connection to that backend, so your devices do not need to share the same Wi-Fi.</p>
      <figure className="panel my-8 p-5 md:p-8">
        <svg role="img" aria-labelledby="connection-title connection-description" viewBox="0 0 780 180" className="w-full">
          <title id="connection-title">Laptop app connects to cloud and phone browser</title>
          <desc id="connection-description">The laptop app and phone browser each connect securely to the cloud backend. They do not connect directly to each other.</desc>
          <g fill="none" stroke="currentColor" strokeWidth="3">
            <path d="M175 90h190M415 90h190" stroke="#6ce5f3" strokeDasharray="8 7"/>
            <rect x="25" y="38" width="150" height="104" rx="14" stroke="#6ce5f3"/>
            <rect x="315" y="38" width="150" height="104" rx="14" stroke="#6ce5f3"/>
            <rect x="605" y="38" width="150" height="104" rx="14" stroke="#6ce5f3"/>
          </g>
          <g fill="currentColor" fontFamily="Arial, sans-serif" textAnchor="middle">
            <text x="100" y="82" fontSize="17" fontWeight="700">Laptop app</text><text x="100" y="108" fontSize="13">Windows PC</text>
            <text x="390" y="82" fontSize="17" fontWeight="700">Cloud backend</text><text x="390" y="108" fontSize="13">HTTPS + WSS</text>
            <text x="680" y="82" fontSize="17" fontWeight="700">Phone browser</text><text x="680" y="108" fontSize="13">Dashboard / PWA</text>
          </g>
        </svg>
        <figcaption className="muted mt-3 text-center text-sm">Both devices make an encrypted connection to the backend; no direct LAN connection is needed.</figcaption>
      </figure>
      <ol className="space-y-5 pl-6 leading-7">
        <li><strong>Install the Windows app.</strong> Download it from the <Link href="/download">official download page</Link> and keep it running on your PC.</li>
        <li><strong>Sign in from your phone.</strong> Visit this site and select <strong>Try JARVIS</strong>. You can add the site to your phone’s home screen for an app-like shortcut.</li>
        <li><strong>Create a code.</strong> Open <Link href="/app/devices">Dashboard → Devices</Link>, choose <strong>Create pairing code</strong>, and copy the 8-character code.</li>
        <li><strong>Pair the PC.</strong> In the desktop app, enter the backend URL shown by your administrator and the code. It expires after 10 minutes and works once.</li>
        <li><strong>Start chatting.</strong> Add an AI provider key in <Link href="/app/settings/keys">API key settings</Link>, then send a message from the dashboard.</li>
      </ol>
      <aside className="panel mt-8 p-5">
        <h2 className="font-bold">Keep in mind</h2>
        <p className="muted mt-2 leading-7">Your laptop must be turned on, online, and running the JARVIS desktop app. The phone and PC do not need the same Wi-Fi, but both need internet access to reach the configured backend.</p>
      </aside>
    </main>
  );
}
