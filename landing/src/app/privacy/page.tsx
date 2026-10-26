import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Privacy notice (draft)" };

export default function PrivacyPage() {
  return (
    <main className="site-width max-w-4xl py-10 md:py-16">
      <Link href="/" className="text-sm">← Home</Link>
      <p className="section-kicker mt-8">LEGAL · DRAFT</p>
      <h1 className="mt-3 text-4xl font-bold tracking-tight">Privacy notice</h1>
      <p className="muted mt-3 font-semibold">Draft — review before launch</p>
      <p className="muted mt-6 leading-7">This draft describes the current JARVIS setup at a high level. It is not legal advice and must be reviewed and completed before public launch, including details about the operator, hosting region, retention periods, and applicable rights.</p>
      <div className="panel mt-7 space-y-6 p-6 leading-7">
        <section><h2 className="font-bold">Sign-in and account</h2><p className="muted mt-2">Sign-in is handled by Clerk. JARVIS uses the authenticated account identity to associate dashboard data with your account.</p></section>
        <section><h2 className="font-bold">Data and storage</h2><p className="muted mt-2">The service is configured to store application data in a Neon-hosted PostgreSQL database. Depending on features used, this can include account-associated chat and device information. Provider API keys are stored by the backend in encrypted form; the encryption key is managed by the operator.</p></section>
        <section><h2 className="font-bold">AI providers and images</h2><p className="muted mt-2">When you use AI features, your request is sent to the provider configured for your account. If you explicitly request a camera capture, the captured image is sent to the vision model you configured. Review that provider’s terms and privacy practices before use.</p></section>
        <section><h2 className="font-bold">Paired devices and camera</h2><p className="muted mt-2">You can revoke paired devices. The Windows client camera is off when the app launches and requires a request and user approval before capture.</p></section>
        <section><h2 className="font-bold">Items to complete before launch</h2><p className="muted mt-2">The operator must add contact details, exact retention/deletion rules, hosting and subprocessors, cookie/analytics details if applicable, and the process for privacy requests after reviewing the deployed configuration.</p></section>
      </div>
      <p className="mt-6"><Link href="/terms">Read the draft terms of service</Link></p>
    </main>
  );
}
