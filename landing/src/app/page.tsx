import Link from "next/link";
import { SignInButton } from "@clerk/nextjs";

const features = [
  {
    number: "01",
    title: "Talk to your assistant",
    description: "Connect your own supported AI provider key and chat from the JARVIS dashboard.",
    icon: "chat",
  },
  {
    number: "02",
    title: "Reach your Windows PC",
    description: "Pair the desktop client with a one-time code to make supported device actions available.",
    icon: "desktop",
  },
  {
    number: "03",
    title: "Stay in control",
    description: "Review permissions, approve sensitive actions, and revoke a paired device whenever you need.",
    icon: "shield",
  },
  {
    number: "04",
    title: "Choose when to use the camera",
    description: "Camera access is off at launch and is only used when you request a capture.",
    icon: "camera",
  },
] as const;

const steps = [
  ["Sign in", "Open your JARVIS dashboard in a browser."],
  ["Pair your PC", "Install the Windows client and enter a one-time pairing code."],
  ["Make it yours", "Save your own provider key, then start a conversation."],
];

function FeatureIcon({ name }: { name: (typeof features)[number]["icon"] }) {
  const paths = {
    chat: <><path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5H5l-2 2v-6.5A7.5 7.5 0 1 1 20 11.5Z" /><path d="M8 11h.01M12 11h.01M16 11h.01" /></>,
    desktop: <><rect x="3" y="4" width="18" height="13" rx="2" /><path d="M8 21h8m-4-4v4" /></>,
    shield: <><path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z" /><path d="m9 12 2 2 4-4" /></>,
    camera: <><path d="M14 5h-4L8 8H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-9a2 2 0 0 0-2-2h-4l-2-3Z" /><circle cx="12" cy="13.5" r="3.5" /></>,
  };

  return (
    <svg aria-hidden="true" className="h-6 w-6" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" viewBox="0 0 24 24">
      {paths[name]}
    </svg>
  );
}

export default function HomePage() {
  return (
    <main>
      <header className="site-width flex items-center justify-between py-5 md:py-6">
        <Link href="/" aria-label="JARVIS home" className="flex items-center gap-3 text-[var(--ink)] no-underline">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--accent)] text-white shadow-sm">
            <svg aria-hidden="true" className="h-6 w-6" fill="none" viewBox="0 0 24 24">
              <path d="M12 2.8 20 7v5.2c0 4.5-3.2 7.7-8 9-4.8-1.3-8-4.5-8-9V7l8-4.2Z" stroke="currentColor" strokeWidth="1.6" />
              <path d="M8.5 12h7M12 8.5v7" stroke="currentColor" strokeLinecap="round" strokeWidth="1.6" />
            </svg>
          </span>
          <span className="text-sm font-extrabold tracking-[0.18em]">J.A.R.V.I.S.</span>
        </Link>
        <nav aria-label="Main navigation" className="flex items-center gap-4 text-sm sm:gap-7">
          <Link className="hidden text-[var(--muted)] no-underline hover:text-[var(--ink)] sm:inline" href="#features">Features</Link>
          <Link className="hidden text-[var(--muted)] no-underline hover:text-[var(--ink)] sm:inline" href="/docs/connect">How it works</Link>
          <Link className="text-[var(--muted)] no-underline hover:text-[var(--ink)]" href="/download">Download</Link>
          <SignInButton mode="modal" forceRedirectUrl="/app">
            <button className="button-primary min-h-10 px-4 py-2">Sign in</button>
          </SignInButton>
        </nav>
      </header>

      <section className="site-width grid items-center gap-12 pb-16 pt-10 md:min-h-[650px] md:grid-cols-[1.05fr_0.95fr] md:gap-8 md:pb-24 md:pt-12">
        <div className="relative z-10">
          <p className="mb-5 inline-flex items-center gap-2 rounded-full border border-[var(--line)] bg-white/70 px-3 py-1.5 text-xs font-bold uppercase tracking-[0.16em] text-[var(--accent)]">
            <span aria-hidden="true" className="h-2 w-2 rounded-full bg-[var(--accent)]" />
            Your assistant, on your terms
          </p>
          <h1 className="max-w-2xl text-5xl font-extrabold leading-[1.04] tracking-[-0.045em] sm:text-6xl md:text-7xl">
            Your AI. Your PC. <span className="text-[var(--accent)]">Connected.</span>
          </h1>
          <p className="muted mt-6 max-w-xl text-lg leading-8">
            J.A.R.V.I.S. brings an AI chat dashboard and a paired Windows desktop client together. Choose your provider, decide what to connect, and stay in control.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <SignInButton mode="modal" forceRedirectUrl="/app">
              <button className="button-primary gap-2 px-5">
                Open dashboard
                <span aria-hidden="true">→</span>
              </button>
            </SignInButton>
            <Link className="button-secondary gap-2 px-5" href="/download">
              Download for Windows
              <span aria-hidden="true">↓</span>
            </Link>
          </div>
          <p className="muted mt-4 text-sm">Bring your own provider key. No key is bundled with J.A.R.V.I.S.</p>
          <div className="mt-9 flex flex-wrap items-center gap-x-6 gap-y-3 text-sm font-medium text-[var(--ink)]">
            <span className="inline-flex items-center gap-2"><span className="text-[var(--accent)]">✓</span> Permission-controlled actions</span>
            <span className="inline-flex items-center gap-2"><span className="text-[var(--accent)]">✓</span> Camera off at launch</span>
          </div>
        </div>

        <div className="relative mx-auto w-full max-w-[520px]">
          <div aria-hidden="true" className="absolute -inset-8 rounded-[3rem] bg-[var(--accent)] opacity-[0.07] blur-2xl" />
          <div className="panel relative overflow-hidden rounded-3xl border-white/80 p-5 shadow-[0_28px_80px_rgba(7,27,53,0.12)] sm:p-7">
            <div className="flex items-center justify-between border-b border-[var(--line)] pb-4">
              <div className="flex items-center gap-3">
                <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[var(--accent)] text-sm font-bold text-white">J</span>
                <div><p className="text-sm font-bold">J.A.R.V.I.S.</p><p className="muted text-xs">Assistant workspace</p></div>
              </div>
              <span className="rounded-full border border-[var(--line)] bg-[var(--panel-raised)] px-3 py-1 text-xs font-semibold text-[var(--muted)]">Preview</span>
            </div>
            <div className="py-7">
              <p className="muted text-xs font-bold uppercase tracking-[0.18em]">A workspace shaped around your choices</p>
              <div className="mt-5 max-w-[90%] rounded-2xl rounded-tl-sm bg-[var(--panel-raised)] p-4 text-sm leading-6">
                What would you like to work on?
              </div>
              <div className="ml-auto mt-4 max-w-[85%] rounded-2xl rounded-tr-sm bg-[var(--accent)] p-4 text-sm leading-6 text-white">
                Check in with my connected PC.
              </div>
              <div className="mt-4 flex max-w-[90%] items-start gap-3 rounded-2xl rounded-tl-sm border border-[var(--line)] bg-white p-4 text-sm leading-6">
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-[var(--accent)] text-xs font-bold text-white">J</span>
                Pair a Windows device to make supported actions available here.
              </div>
            </div>
            <div className="flex items-center gap-3 rounded-xl border border-[var(--line)] bg-white p-3">
              <span className="muted flex-1 px-1 text-sm">Message your assistant…</span>
              <span aria-hidden="true" className="flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--accent)] text-white">↑</span>
            </div>
            <p className="muted mt-3 text-center text-xs">Illustrative preview · not a live connection</p>
          </div>
          <div className="panel absolute -bottom-5 -left-5 hidden items-center gap-3 rounded-2xl px-4 py-3 shadow-lg sm:flex">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-50 text-[var(--accent)]">
              <FeatureIcon name="shield" />
            </span>
            <span><span className="block text-sm font-bold">You stay in control</span><span className="muted block text-xs">Permissions when they matter</span></span>
          </div>
        </div>
      </section>

      <section id="features" aria-labelledby="features-heading" className="border-y border-[var(--line)] bg-white/60 py-16 md:py-20">
        <div className="site-width">
          <div className="max-w-2xl">
            <p className="section-kicker">Designed around your choices</p>
            <h2 id="features-heading" className="mt-3 text-3xl font-extrabold tracking-tight sm:text-4xl">Useful connections. Clear controls.</h2>
            <p className="muted mt-4 leading-7">Connect only what you choose, with the permissions and setup steps visible along the way.</p>
          </div>
          <ul className="mt-9 grid list-none gap-4 p-0 sm:grid-cols-2 lg:grid-cols-4">
            {features.map((feature) => (
              <li className="panel rounded-2xl p-5 transition-transform duration-200 hover:-translate-y-1" key={feature.number}>
                <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-blue-50 text-[var(--accent)]"><FeatureIcon name={feature.icon} /></span>
                <p className="mt-5 text-xs font-bold tracking-[0.12em] text-[var(--accent)]">{feature.number}</p>
                <h3 className="mt-2 text-lg font-bold">{feature.title}</h3>
                <p className="muted mt-2 text-sm leading-6">{feature.description}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="site-width py-16 md:py-20" aria-labelledby="getting-started-heading">
        <div className="grid gap-10 md:grid-cols-[0.8fr_1.2fr] md:items-center">
          <div>
            <p className="section-kicker">Getting started</p>
            <h2 id="getting-started-heading" className="mt-3 text-3xl font-extrabold tracking-tight sm:text-4xl">Three steps to your workspace.</h2>
            <p className="muted mt-4 leading-7">The dashboard connects to the backend you configure. Your Windows client must be online for its device features.</p>
            <Link href="/docs/connect" className="mt-6 inline-flex items-center gap-2 font-bold text-[var(--accent)] no-underline hover:text-[var(--accent-hover)]">
              Read the connection guide <span aria-hidden="true">→</span>
            </Link>
          </div>
          <ol className="m-0 grid list-none gap-3 p-0 sm:grid-cols-3">
            {steps.map(([title, description], index) => (
              <li className="panel rounded-2xl p-5" key={title}>
                <span className="flex h-9 w-9 items-center justify-center rounded-full bg-[var(--accent)] text-sm font-bold text-white">{index + 1}</span>
                <h3 className="mt-5 font-bold">{title}</h3>
                <p className="muted mt-2 text-sm leading-6">{description}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="site-width pb-16 md:pb-20">
        <div className="flex flex-col justify-between gap-6 rounded-3xl bg-[var(--navy)] p-7 text-white sm:p-10 md:flex-row md:items-center">
          <div className="max-w-2xl">
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-blue-200">Start when you are ready</p>
            <h2 className="mt-3 text-2xl font-extrabold sm:text-3xl">Your assistant. Your setup.</h2>
            <p className="mt-3 text-sm leading-6 text-blue-100">Sign in to open the dashboard, or get the Windows client for the PC you want to connect.</p>
          </div>
          <div className="flex shrink-0 flex-wrap gap-3">
            <SignInButton mode="modal" forceRedirectUrl="/app">
              <button className="button-primary border-white bg-white text-[var(--navy)] hover:bg-blue-50">Open dashboard</button>
            </SignInButton>
            <Link className="button-secondary border-white/30 bg-white/10 text-white hover:bg-white/15" href="/download">Windows download</Link>
          </div>
        </div>
      </section>

      <footer className="border-t border-[var(--line)] bg-white/50">
        <div className="site-width flex flex-col gap-4 py-6 text-sm sm:flex-row sm:items-center sm:justify-between">
          <Link href="/" className="font-bold tracking-[0.16em] text-[var(--ink)] no-underline">J.A.R.V.I.S.</Link>
          <nav aria-label="Footer navigation" className="flex flex-wrap gap-x-5 gap-y-2">
            <Link href="/docs/connect">Connection guide</Link>
            <Link href="/docs/api-keys">Provider key guide</Link>
            <Link href="/download">Windows download</Link>
          </nav>
          <p className="muted">Built by Hammad</p>
        </div>
      </footer>
    </main>
  );
}
