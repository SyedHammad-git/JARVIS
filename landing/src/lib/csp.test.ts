import { describe, expect, it } from "vitest";
import { clerkFrontendApiDomain, contentSecurityPolicy } from "./csp";

const frontendApiDomain = "test-instance.clerk.accounts.dev";
const backendOrigin = "http://localhost:5000";

function parsePolicy(policy: string): Map<string, string[]> {
  return new Map(
    policy.split(";").map((directive) => {
      const [name, ...sources] = directive.trim().split(/\s+/);
      return [name, sources];
    }),
  );
}

describe("content security policy", () => {
  it("decodes the Clerk Frontend API domain from its publishable key", () => {
    const key = `pk_test_${btoa(`${frontendApiDomain}$`)}`;
    expect(clerkFrontendApiDomain(key)).toBe(frontendApiDomain);
  });

  it("allows development evaluation and HMR while retaining Clerk and backend sources", () => {
    const policy = parsePolicy(contentSecurityPolicy({
      nonce: "test-nonce",
      backendOrigin,
      clerkFrontendApiDomain: frontendApiDomain,
      development: true,
    }));

    expect(policy.get("script-src")).toEqual(expect.arrayContaining([
      "'unsafe-eval'",
      `https://${frontendApiDomain}`,
      "https://challenges.cloudflare.com",
    ]));
    expect(policy.get("connect-src")).toEqual(expect.arrayContaining([
      backendOrigin,
      `https://${frontendApiDomain}`,
      "https://challenges.cloudflare.com",
      "ws://localhost:3000",
      "ws://127.0.0.1:3000",
    ]));
    expect(policy.get("img-src")).toContain("https://img.clerk.com");
    expect(policy.get("frame-src")).toContain("https://challenges.cloudflare.com");
    expect(policy.get("worker-src")).toEqual(["'self'", "blob:"]);
  });

  it("keeps production strict, exact-host-only, and allows Clerk and backend sources", () => {
    const policy = contentSecurityPolicy({
      nonce: "test-nonce",
      backendOrigin,
      clerkFrontendApiDomain: frontendApiDomain,
      development: false,
    });
    const parsed = parsePolicy(policy);

    expect(parsed.get("script-src")).not.toContain("'unsafe-eval'");
    expect(parsed.get("script-src")).toEqual(expect.arrayContaining([
      `https://${frontendApiDomain}`,
      "https://challenges.cloudflare.com",
    ]));
    expect(policy).not.toContain("*");
    expect(parsed.get("connect-src")).toEqual(expect.arrayContaining([
      backendOrigin,
      `https://${frontendApiDomain}`,
    ]));
    expect(parsed.get("img-src")).toEqual(expect.arrayContaining([
      `https://${frontendApiDomain}`,
      "https://img.clerk.com",
    ]));
    expect(parsed.get("frame-src")).toContain("https://challenges.cloudflare.com");
    expect(parsed.get("worker-src")).toEqual(["'self'", "blob:"]);
  });
});
