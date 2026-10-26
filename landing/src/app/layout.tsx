import type { Metadata, Viewport } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import localFont from "next/font/local";
import { AuthRedirectHandler } from "@/components/AuthRedirectHandler";
import "./globals.css";

const configuredSiteUrl = process.env.NEXT_PUBLIC_SITE_URL;

const inter = localFont({
  src: "../../node_modules/@fontsource-variable/inter/files/inter-latin-wght-normal.woff2",
  weight: "100 900",
  style: "normal",
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: configuredSiteUrl ? new URL(configuredSiteUrl) : undefined,
  title: {
    default: "J.A.R.V.I.S. — Your desktop, within reach",
    template: "%s | J.A.R.V.I.S.",
  },
  description: "A personal AI dashboard for your chosen AI provider and paired Windows desktop client.",
  openGraph: {
    type: "website",
    title: "J.A.R.V.I.S. — Your desktop, within reach",
    description: "A personal AI dashboard for your chosen AI provider and paired Windows desktop client.",
  },
  twitter: {
    card: "summary_large_image",
    title: "J.A.R.V.I.S. — Your desktop, within reach",
    description: "A personal AI dashboard for your chosen AI provider and paired Windows desktop client.",
  },
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "JARVIS", statusBarStyle: "black-translucent" },
  icons: {
    icon: [
      { url: "/icons/jarvis.svg", type: "image/svg+xml" },
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
      <body className={inter.variable}>
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
