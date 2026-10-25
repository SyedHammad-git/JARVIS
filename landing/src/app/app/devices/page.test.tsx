import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DevicesPage from "./page";

const { getToken } = vi.hoisted(() => ({ getToken: vi.fn().mockResolvedValue("mock-session-token") }));
vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken }) }));

describe("device pairing flow", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_BACKEND_URL", "https://backend.test");
    getToken.mockResolvedValue("mock-session-token");
  });

  it("requests and displays an eight-character code with a ten-minute expiry", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith("/api/devices/pair-code")) {
        expect(init?.method).toBe("POST");
        expect(JSON.parse(String(init?.body))).toEqual({ name: "PC" });
        return new Response(JSON.stringify({ code: "ABC234DE", expires_at: Date.now() / 1000 + 600 }), { status: 200 });
      }
      return new Response(JSON.stringify({ devices: [] }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<DevicesPage />);

    await user.click(screen.getByRole("button", { name: "Create pairing code" }));

    expect(await screen.findByLabelText("Pairing code")).toHaveTextContent("ABC234DE");
    expect(screen.getByText(/Expires in \d{1,2}:\d{2}/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy code" })).toBeInTheDocument();
    expect(screen.getByText(/provided by your administrator/)).toBeInTheDocument();
  });
});
