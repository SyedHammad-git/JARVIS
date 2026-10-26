import type { Metadata, Viewport } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import { AuthRedirectHandler } from "@/components/AuthRedirectHandler";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "J.A.R.V.I.S. — Your desktop, within reach",
    template: "%s | J.A.R.V.I.S.",
  },
  description: "A private, multi-model assistant for your Windows PC, accessible from your phone.",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "JARVIS", statusBarStyle: "black-translucent" },
  icons: {
    icon: [
      { url: "/icons/jarvis-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icons/jarvis-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: [{ url: "/icons/jarvis-192.png", sizes: "192x192", type: "image/png" }],
  },
};

export const viewport: Viewport = {
  themeColor: [{ media: "(prefers-color-scheme: dark)", color: "#07111f" }, { media: "(prefers-color-scheme: light)", color: "#f5f8fc" }],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <ClerkProvider
          dynamic
          signInUrl="/sign-in"
          signUpUrl="/sign-in"
          publishableKey={process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY}
        >
          <AuthRedirectHandler />
          {children}
        </ClerkProvider>
      </body>
    </html>
  );
}
