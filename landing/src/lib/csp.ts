type ContentSecurityPolicyOptions = {
  nonce: string;
  backendOrigin: string;
  clerkFrontendApiDomain: string;
  development: boolean;
};

export function clerkFrontendApiDomain(publishableKey: string | undefined): string {
  if (!publishableKey) {
    throw new Error("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY is required to configure the CSP");
  }

  const encodedDomain = publishableKey
    .replace(/^pk_(?:test|live)_/, "")
    .replace(/\$$/, "");
  if (encodedDomain === publishableKey) {
    throw new Error("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY has an invalid format");
  }

  try {
    const base64 = encodedDomain.replace(/-/g, "+").replace(/_/g, "/");
    const decoded = atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, "="))
      .replace(/\$$/, "");
    const url = new URL(`https://${decoded}`);
    if (url.hostname !== decoded || url.pathname !== "/" || url.port) {
      throw new Error("invalid Clerk Frontend API domain");
    }
    return url.hostname;
  } catch {
    throw new Error("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY has an invalid format");
  }
}

export function contentSecurityPolicy({
  nonce,
  backendOrigin,
  clerkFrontendApiDomain: frontendApiDomain,
  development,
}: ContentSecurityPolicyOptions): string {
  const frontendApi = `https://${frontendApiDomain}`;
  const devConnectSources = development
    ? ["ws://localhost:3000", "ws://127.0.0.1:3000"]
    : [];
  const scriptSources = [
    "'self'",
    `'nonce-${nonce}'`,
    "'strict-dynamic'",
    ...(development ? ["'unsafe-eval'"] : []),
    frontendApi,
    "https://challenges.cloudflare.com",
  ];

  return [
    "default-src 'self'",
    `script-src ${scriptSources.join(" ")}`,
    `style-src 'self' 'unsafe-inline' ${frontendApi}`,
    `img-src 'self' data: blob: ${frontendApi} https://img.clerk.com`,
    `connect-src 'self' ${backendOrigin} ${frontendApi} https://challenges.cloudflare.com ${devConnectSources.join(" ")}`.trim(),
    `frame-src 'self' ${frontendApi} https://challenges.cloudflare.com`,
    "worker-src 'self' blob:",
    "font-src 'self' data:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    ...(development ? [] : ["upgrade-insecure-requests"]),
  ].join("; ");
}
