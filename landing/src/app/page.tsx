import Link from "next/link";
import { SiteHeader } from "@/components/SiteHeader";
import { AuthAction } from "@/components/AuthAction";

const features = [
  {
    icon: "✦",
    title: "Talk to your assistant",
    description: "Chat from a browser with the AI provider and model you choose, using your own API key.",
  },
  {
    icon: "⌘",
    title: "Reach your Windows PC",
    description: "Pair the desktop app to send supported tasks to your computer when it is online.",
  },
  {
    icon: "◉",
    title: "Stay in control",
    description: "Review confirmation prompts for sensitive actions and revoke a paired device at any time.",
  },
  {
    icon: "▣",
    title: "Camera only on request",
    description: "The camera starts off. A capture needs your approval and is sent to your configured vision model.",
  },
];

function LaptopPreview() {
  return (
    <div className="device-preview" aria-label="Illustrative JARVIS browser dashboard preview">
      <div className="preview-glow" aria-hidden="true" />
      <div className="laptop">
        <div className="laptop-screen">
          <div className="preview-window">
            <div className="preview-topbar"><span /><span /><span /><i>J.A.R.V.I.S.</i></div>
            <div className="preview-layout">
              <div className="preview-sidebar"><b>J</b><span /><span /><span /></div>
              <div className="preview-chat">
                <small>PERSONAL DASHBOARD</small>
                <strong>Good to see you.</strong>
                <div className="preview-bubble preview-user">What’s on my schedule today?</div>
                <div className="preview-bubble preview-answer">I can help with that. Connect a calendar or ask me anything.</div>
                <div className="preview-input">Message JARVIS <span>↑</span></div>
              </div>
            </div>
          </div>
        </div>
        <div className="laptop-base" />
      </div>
      <div className="phone">
        <div className="phone-notch" />
        <small>J.A.R.V.I.S.</small>
        <b>Your devices</b>
        <div className="phone-device"><span className="device-dot" /> My Windows PC <em>Online</em></div>
        <div className="phone-action">Ask JARVIS anything <span>↑</span></div>
      </div>
      <p className="preview-caption">Illustrative preview — not a live connection</p>
    </div>
  );
}

function ConnectionFlow() {
  return (
    <div className="connection-flow" aria-label="Laptop and phone connect to JARVIS through the cloud">
      <div className="flow-device"><span aria-hidden="true">▱</span><b>Your laptop</b><small>Windows app</small></div>
      <div className="flow-link" aria-hidden="true"><span /></div>
      <div className="flow-cloud"><span aria-hidden="true">☁</span><b>JARVIS cloud</b><small>Encrypted connection</small></div>
      <div className="flow-link" aria-hidden="true"><span /></div>
      <div className="flow-device"><span aria-hidden="true">▯</span><b>Your phone</b><small>Web dashboard</small></div>
    </div>
  );
}

export default function HomePage() {
  return (
    <>
      <SiteHeader />
      <main>
        <section className="hero site-width">
          <div className="hero-copy">
            <p className="section-kicker"><span className="kicker-dot" /> YOUR AI, CONNECTED TO YOUR DESKTOP</p>
            <h1>Your AI.<br />Your PC.<br /><span>Connected.</span></h1>
            <p className="hero-description">A personal AI dashboard that brings your chosen AI provider and paired Windows PC into one place.</p>
            <div className="hero-actions">
              <AuthAction label="Try JARVIS" className="button-primary" />
              <Link className="button-secondary" href="/download">Download for Windows <span aria-hidden="true">↓</span></Link>
            </div>
            <p className="hero-note">Bring your own provider key · Camera off at launch · Revoke devices any time</p>
          </div>
          <LaptopPreview />
        </section>

        <section className="feature-section" id="features" role="region" aria-label="Useful connections. Clear controls." aria-labelledby="features-title">
          <div className="site-width section-block">
            <div className="section-heading">
              <p className="section-kicker">MADE FOR YOUR WORKFLOW</p>
              <h2 id="features-title">Useful connections.<br /><span>Clear controls.</span></h2>
              <p className="muted">A focused dashboard for the assistant you configure and the devices you choose to pair.</p>
            </div>
            <div className="feature-grid">
              {features.map((feature) => (
                <article className="feature-card" key={feature.title}>
                  <span className="feature-icon" aria-hidden="true">{feature.icon}</span>
                  <h3>{feature.title}</h3>
                  <p>{feature.description}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="site-width section-block more-section" aria-labelledby="more-title">
          <div className="section-heading section-heading-centered">
            <p className="section-kicker">ONE DASHBOARD, YOUR CHOICE</p>
            <h2 id="more-title">More than just an<br /><span>AI assistant.</span></h2>
            <p className="muted">Use your own provider credentials, connect your own devices, and keep important actions visible.</p>
          </div>
          <article className="connection-card panel">
            <div className="connection-copy">
              <span className="feature-icon" aria-hidden="true">⌁</span>
              <h3>Connect your devices</h3>
              <p className="muted">Your Windows app and phone dashboard each connect to the configured backend. Pairing is controlled from your account, and a device can be revoked.</p>
              <Link href="/docs/connect" className="text-link">See how device pairing works <span aria-hidden="true">→</span></Link>
            </div>
            <ConnectionFlow />
          </article>
          <div className="capability-grid">
            <article className="capability-card panel">
              <span className="feature-icon" aria-hidden="true">✧</span>
              <p className="section-kicker">YOUR PROVIDER, YOUR KEY</p>
              <h3>Choose an AI model</h3>
              <p className="muted">Configure your own key for a supported provider. Available integrations include Groq, Gemini, and OpenRouter.</p>
              <div className="provider-list" aria-label="Supported AI providers"><span>Groq</span><span>Gemini</span><span>OpenRouter</span></div>
            </article>
            <article className="capability-card camera-card panel">
              <span className="feature-icon" aria-hidden="true">◎</span>
              <p className="section-kicker">PERMISSION FIRST</p>
              <h3>Smart camera access</h3>
              <p className="muted">Camera access is off when the desktop app launches. You initiate a capture; captured images are sent to the vision model you configured.</p>
              <span className="camera-state"><i aria-hidden="true" /> Off until requested</span>
            </article>
          </div>
        </section>

        <section className="download-section" id="download" aria-labelledby="download-title">
          <div className="site-width download-inner">
            <div>
              <p className="section-kicker">READY WHEN YOU ARE</p>
              <h2 id="download-title">Bring your PC<br />into the conversation.</h2>
              <p className="muted">Install the Windows desktop app, pair it with your account, and keep it running when you want to use desktop actions.</p>
              <Link className="button-primary" href="/download">Get JARVIS for Windows <span aria-hidden="true">↓</span></Link>
            </div>
            <ol className="install-steps">
              <li><span>01</span><div><b>Download</b><p>Get the current Windows installer from the download page.</p></div></li>
              <li><span>02</span><div><b>Install</b><p>Run the installer and open the JARVIS desktop app.</p></div></li>
              <li><span>03</span><div><b>Pair your PC</b><p>Create a one-time pairing code in your dashboard and enter it in the app.</p></div></li>
              <li><span>04</span><div><b>Add your provider key</b><p>Save your own supported AI provider key in account settings.</p></div></li>
            </ol>
          </div>
        </section>

        <section className="honesty-section site-width" aria-label="About JARVIS">
          <div className="honesty-mark" aria-hidden="true">J</div>
          <div><p className="section-kicker">A PROJECT IN PROGRESS</p><h2>Built by Hammad,<br />open to feedback.</h2><p className="muted">JARVIS is actively being developed. Explore the setup guides and try the current build to see how it works today.</p></div>
          <Link href="/docs" className="button-secondary">Read the docs <span aria-hidden="true">→</span></Link>
        </section>
      </main>
      <footer className="site-footer">
        <div className="site-width">
          <div className="footer-main">
            <div className="footer-brand"><Link href="/" className="brand-lockup"><span className="brand-mark">J</span><span>J.A.R.V.I.S.</span></Link><p>A personal AI dashboard for your connected devices.</p></div>
            <div className="footer-links"><div><h2>Quick links</h2><Link href="/#features">Features</Link><Link href="/download">Download</Link><Link href="/docs">Documentation</Link></div><div><h2>Support</h2><Link href="/docs/connect">Connection guide</Link><Link href="/privacy">Privacy (draft)</Link><Link href="/terms">Terms (draft)</Link></div></div>
          </div>
          <div className="footer-bottom"><span>© {new Date().getFullYear()} J.A.R.V.I.S.</span><span>Sign-in handled by Clerk · Production application data stored in Neon.</span></div>
        </div>
      </footer>
    </>
  );
}
