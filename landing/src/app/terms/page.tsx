import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Terms of service (draft)" };

export default function TermsPage() {
  return (
    <main className="site-width max-w-4xl py-10 md:py-16">
      <Link href="/" className="text-sm">← Home</Link>
      <p className="section-kicker mt-8">LEGAL · DRAFT</p>
      <h1 className="mt-3 text-4xl font-bold tracking-tight">Terms of service</h1>
      <p className="muted mt-3 font-semibold">Draft — review before launch</p>
      <p className="muted mt-6 leading-7">This draft is a starting point, not a complete agreement or legal advice. It must be reviewed and completed by the operator before public launch.</p>
      <div className="panel mt-7 space-y-6 p-6 leading-7">
        <section><h2 className="font-bold">Use of the service</h2><p className="muted mt-2">JARVIS is a software project that connects a web dashboard, configured AI providers, and paired Windows devices. Use it only with accounts, devices, and services you are authorized to access.</p></section>
        <section><h2 className="font-bold">Your configuration and providers</h2><p className="muted mt-2">You provide and manage your own AI provider credentials. Your use of each external provider is also subject to that provider’s terms. Consider the data you send before using an AI feature.</p></section>
        <section><h2 className="font-bold">Device actions and camera</h2><p className="muted mt-2">Review device actions and confirmation prompts before approving them. Camera capture is not automatic; it requires a request and user approval, and captured images are sent to your configured vision model.</p></section>
        <section><h2 className="font-bold">Availability and operator details</h2><p className="muted mt-2">No uptime or uninterrupted availability is promised by this draft. Before launch, the operator must add legal identity and contact details, governing law, dispute terms, warranty/liability language, acceptable-use requirements, and termination/deletion procedures.</p></section>
      </div>
      <p className="mt-6"><Link href="/privacy">Read the draft privacy notice</Link></p>
    </main>
  );
}
