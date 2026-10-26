import React from "react";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import HomePage from "./page";

vi.mock("@clerk/nextjs", () => ({
  SignInButton: ({ children }: { children: React.ReactNode }) => children,
}));

afterEach(cleanup);

describe("landing page", () => {
  it("introduces the product with honest setup and permission details", () => {
    render(<HomePage />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Your AI. Your PC. Connected.");
    expect(screen.getByText(/Bring your own provider key/)).toBeInTheDocument();
    expect(screen.getByText(/Illustrative preview · not a live connection/)).toBeInTheDocument();
    expect(screen.getByText(/Camera access is off at launch/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download for Windows" })).toHaveAttribute("href", "/download");
  });

  it("shows feature cards and working setup guides", () => {
    render(<HomePage />);

    const features = screen.getByRole("region", { name: "Useful connections. Clear controls." });
    expect(within(features).getByRole("heading", { name: "Talk to your assistant" })).toBeInTheDocument();
    expect(within(features).getByRole("heading", { name: "Reach your Windows PC" })).toBeInTheDocument();
    expect(within(features).getByRole("heading", { name: "Stay in control" })).toBeInTheDocument();
    expect(within(features).getByRole("heading", { name: "Choose when to use the camera" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /connection guide/i })[0]).toHaveAttribute("href", "/docs/connect");
    expect(screen.getByRole("link", { name: "Provider key guide" })).toHaveAttribute("href", "/docs/api-keys");
  });
});
