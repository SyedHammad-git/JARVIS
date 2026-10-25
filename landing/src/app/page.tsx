import Link from "next/link";
import { SignInButton } from "@clerk/nextjs";

const features = [
  ["Control your PC from your phone", "Send commands to your paired Windows desktop from any browser."],
  ["Multi-model AI", "Connect your own Groq, Gemini, or OpenRouter key and choose the assistant that fits."],
  ["Camera only on request", "Camera access stays permission-gated on the desktop and is used only when you ask."],
  ["Privacy first", "Your provider keys are encrypted by the backend and never saved in browser storage."],
];

export default function HomePage() {
  return (
    <main>
      <header className="site-width flex items-center justify-between py-6">
        <Link href="/" className="text-sm font-bold tracking-[0.22em] text-[var(--ink)] no-underline">J.A.R.V.I.S.</Link>
        <nav aria-label="Main navigation" className="flex items-center gap-5 text-sm">
          <Link href="/docs/connect">Connect guide</Link>
          <Link href="/download">Download</Link>
        </nav>
      </header>

      <section className="site-width grid min-h-[68vh] items-center gap-10 py-14 md:grid-cols-[1.2fr_0.8fr] md:py-20">
        <div>
          <p className="mb-4 text-xs font-bold uppercase tracking-[0.28em] text-[var(--accent)]">Your desktop, within reach</p>
          <h1 className="max-w-3xl text-5xl font-bold leading-[1.05] tracking-tight md:text-7xl">A smarter way to stay connected to your PC.</h1>
          <p className="muted mt-6 max-w-xl text-lg leading-8">J.A.R.V.I.S. brings a personal AI assistant and remote desktop controls together, with the permissions and choices left in your hands.</p>
          <div className="mt-8 flex flex-wrap gap-3">
            <SignInButton mode="modal" forceRedirectUrl="/app">
              <button className="button-primary">Try JARVIS</button>
            </SignInButton>
            <Link className="button-secondary" href="/download">Download for Windows</Link>
          </div>
          <p className="muted mt-4 text-sm">You bring your own AI provider key. No key is included or required to visit.</p>
        </div>
        <div className="panel relative overflow-hidden p-7 md:p-9">
          <div aria-hidden="true" className="absolute -right-10 -top-12 h-48 w-48 rounded-full border border-[var(--line)] opacity-70" />
          <div aria-hidden="true" className="absolute -right-2 -top-4 h-32 w-32 rounded-full border border-[var(--accent)] opacity-30" />
          <p className="text-xs font-bold uppercase tracking-[0.22em] text-[var(--accent)]">JARVIS / READY</p>
          <p className="mt-8 text-2xl font-semibold">“At your service.”</p>
          <p className="muted mt-3 leading-7">A clear path from phone to PC: sign in, pair your device, then choose what to ask.</p>
          <div className="mt-8 border-t border-[var(--line)] pt-5 text-sm">
            <div className="flex justify-between py-2"><span className="muted">Device</span><span>Permission-controlled</span></div>
            <div className="flex justify-between py-2"><span className="muted">AI providers</span><span>Your keys, your choice</span></div>
            <div className="flex justify-between py-2"><span className="muted">Connection</span><span>Encrypted HTTPS</span></div>
          </div>
        </div>
      </section>

      <section className="site-width pb-20">
        <h2 className="mb-7 text-2xl font-bold">Useful by design. Private by default.</h2>
        <ul className="grid list-none gap-4 p-0 sm:grid-cols-2">
          {features.map(([title, description], index) => (
            <li className="panel p-5" key={title}>
              <p className="text-xs font-bold text-[var(--accent)]">0{index + 1}</p>
              <h3 className="mt-3 text-lg font-bold">{title}</h3>
              <p className="muted mt-2 leading-6">{description}</p>
            </li>
          ))}
        </ul>
      </section>
      <footer className="site-width muted border-t border-[var(--line)] py-6 text-sm">
        <Link href="/docs/api-keys">API key guide</Link><span className="px-3">·</span><Link href="/docs/connect">Pairing guide</Link>
      </footer>
    </main>
  );
}
