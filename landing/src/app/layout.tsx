import type { Metadata, Viewport } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import { AuthRedirectHandler } from "@/components/AuthRedirectHandler";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "J.A.R.V.I.S. — Your desktop, within reach",
    template: "%s | J.A.R.V.I.S.",
  },
  description: "A personal AI dashboard that connects to your own provider key and a paired Windows desktop client.",
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
  themeColor: "#F5F9FF",
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
