import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DashboardPage from "./page";

const { getToken } = vi.hoisted(() => ({ getToken: vi.fn().mockResolvedValue("mock-session-token") }));
vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken }) }));

describe("dashboard chat", () => {
  afterEach(() => cleanup());

  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_BACKEND_URL", "https://backend.test");
    getToken.mockResolvedValue("mock-session-token");
  });

  it("shows the API key banner when chat returns no_api_key", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/api/agent")) {
        return new Response(JSON.stringify({ ok: false, error: "no_api_key" }), { status: 400 });
      }
      return new Response(JSON.stringify({ devices: [] }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<DashboardPage />);

    fireEvent.change(screen.getByLabelText("Your message"), { target: { value: "Hello" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Add an AI provider key to begin");
    expect(screen.getByRole("link", { name: "Add an API key →" })).toHaveAttribute("href", "/app/settings/keys");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "https://backend.test/api/agent",
      expect.objectContaining({ method: "POST" }),
    ));
  });

  it("requires explicit confirmation before resubmitting an action", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith("/api/agent")) {
        const request = JSON.parse(String(init?.body)) as { confirmed?: boolean };
        if (request.confirmed) {
          return new Response(JSON.stringify({ ok: true, reply: "Action complete." }), { status: 200 });
        }
        return new Response(JSON.stringify({
          ok: true,
          reply: "Approval is required.",
          needs_confirmation: true,
          confirmation_nonce: "one-time-nonce",
          reason: "high_risk",
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ devices: [] }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<DashboardPage />);

    fireEvent.change(screen.getByLabelText("Your message"), { target: { value: "Open the app" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(await screen.findByRole("heading", { name: "Confirm this action" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm action" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const requests = fetchMock.mock.calls
      .filter(([url]) => String(url).endsWith("/api/agent"))
      .map(([, init]) => JSON.parse(String(init?.body)));
    expect(requests[0]).toMatchObject({ message: "Open the app", confirmed: false });
    expect(requests[1]).toMatchObject({
      message: "Open the app",
      confirmed: true,
      confirmation_nonce: "one-time-nonce",
    });
    expect(await screen.findByText("Action complete.")).toBeInTheDocument();
  });
});
