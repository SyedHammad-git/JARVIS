import { clerkMiddleware } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

function contentSecurityPolicy(nonce: string, backendOrigin: string): string {
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic' https://*.clerk.accounts.dev https://*.clerk.accounts.com https://*.clerk.com`,
    "style-src 'self' 'unsafe-inline' https://*.clerk.accounts.dev https://*.clerk.accounts.com https://*.clerk.com",
    "img-src 'self' data: blob: https://*.clerk.accounts.dev https://*.clerk.accounts.com https://*.clerk.com",
    `connect-src 'self' ${backendOrigin} https://*.clerk.accounts.dev https://*.clerk.accounts.com https://*.clerk.com wss://*.clerk.accounts.dev wss://*.clerk.accounts.com`,
    "frame-src 'self' https://*.clerk.accounts.dev https://*.clerk.accounts.com https://*.clerk.com",
    "font-src 'self' data:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    ...(process.env.NODE_ENV === "production" ? ["upgrade-insecure-requests"] : []),
  ].join("; ");
}

export default clerkMiddleware(async (auth, request) => {
  if (request.nextUrl.pathname.startsWith("/app")) await auth.protect();

  const nonce = btoa(crypto.randomUUID());
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  const backend = process.env.NEXT_PUBLIC_BACKEND_URL;
  let backendOrigin = "'self'";
  if (backend) {
    try {
      backendOrigin = new URL(backend).origin;
    } catch {
      throw new Error("NEXT_PUBLIC_BACKEND_URL must be an absolute URL");
    }
  }
  response.headers.set("Content-Security-Policy", contentSecurityPolicy(nonce, backendOrigin));
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  response.headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  return response;
});

export const config = {
  matcher: ["/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)", "/(api|trpc)(.*)"],
};
