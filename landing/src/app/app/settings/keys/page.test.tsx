import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import KeySettingsPage from "./page";

const { getToken } = vi.hoisted(() => ({ getToken: vi.fn().mockResolvedValue("mock-session-token") }));
vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken }) }));

describe("API key settings flow", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_BACKEND_URL", "https://backend.test");
    getToken.mockResolvedValue("mock-session-token");
  });

  it("loads status, tests a key, saves it, masks it, and deletes it", async () => {
    let configured = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/keys") && init?.method === undefined) {
        return new Response(JSON.stringify({ providers: [{ provider: "groq", configured, last4: configured ? "1234" : "" }] }), { status: 200 });
      }
      if (url.endsWith("/api/keys/groq/test")) {
        expect(JSON.parse(String(init?.body))).toEqual({ key: "test-key-1234" });
        return new Response(JSON.stringify({ valid: true }), { status: 200 });
      }
      if (url.endsWith("/api/keys/groq") && init?.method === "POST") {
        expect(JSON.parse(String(init.body))).toEqual({ key: "provider-secret-1234" });
        configured = true;
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }
      if (url.endsWith("/api/keys/groq") && init?.method === "DELETE") {
        configured = false;
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }
      return new Response(JSON.stringify({ providers: [] }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<KeySettingsPage />);

    const groq = screen.getByRole("region", { name: "Groq" });
    const keyInput = within(groq).getByLabelText("Paste Groq key");
    await user.type(keyInput, "test-key-1234");
    await user.click(within(groq).getByRole("button", { name: "Test key" }));
    expect(await screen.findByText("Key verified with the provider.")).toBeInTheDocument();

    await user.clear(keyInput);
    await user.type(keyInput, "provider-secret-1234");
    await user.click(within(groq).getByRole("button", { name: "Save key" }));
    await waitFor(() => expect(keyInput).toHaveValue(""));
    expect(await within(groq).findByText(/Configured · •••• 1234/)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("provider-secret-1234");

    await user.click(within(groq).getByRole("button", { name: "Delete key" }));
    await waitFor(() => expect(within(groq).getByText("Status: Not configured")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith(
      "https://backend.test/api/keys/groq",
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});
