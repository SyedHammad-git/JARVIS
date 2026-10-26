import { clerkMiddleware } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";
import { clerkFrontendApiDomain, contentSecurityPolicy } from "@/lib/csp";

export default clerkMiddleware(async (auth, request) => {
  if (request.nextUrl.pathname.startsWith("/app")) await auth.protect();

  const nonce = btoa(crypto.randomUUID());
  const backend = process.env.NEXT_PUBLIC_BACKEND_URL;
  let backendOrigin = "'self'";
  if (backend) {
    try {
      backendOrigin = new URL(backend).origin;
    } catch {
      throw new Error("NEXT_PUBLIC_BACKEND_URL must be an absolute URL");
    }
  }
  const policy = contentSecurityPolicy({
    nonce,
    backendOrigin,
    clerkFrontendApiDomain: clerkFrontendApiDomain(
      process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY,
    ),
    development: process.env.NODE_ENV !== "production",
  });
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", policy);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", policy);
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  response.headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  return response;
});

export const config = {
  matcher: ["/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)", "/(api|trpc)(.*)"],
};
