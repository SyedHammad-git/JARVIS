import { SignIn } from "@clerk/nextjs";
import Link from "next/link";

export default function SignInPage() {
  return (
    <main className="site-width flex min-h-screen items-center justify-center py-12">
      <div className="panel w-full max-w-md p-6">
        <Link className="text-sm" href="/">← Back to J.A.R.V.I.S.</Link>
        <h1 className="mt-5 text-2xl font-bold">Sign in</h1>
        <p className="muted mb-6 mt-2">Sign in to open your private dashboard.</p>
        <SignIn routing="hash" forceRedirectUrl="/app" />
      </div>
    </main>
  );
}
