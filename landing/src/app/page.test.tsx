import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import HomePage from "./page";

const { auth, clerk, router } = vi.hoisted(() => ({
  auth: { isLoaded: true, isSignedIn: false },
  clerk: { openSignIn: vi.fn(), openSignUp: vi.fn() },
  router: { push: vi.fn() },
}));

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => auth,
  useClerk: () => clerk,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => router,
}));

afterEach(() => {
  cleanup();
  window.localStorage.removeItem("jarvis-theme");
  delete document.documentElement.dataset.theme;
  vi.clearAllMocks();
});

beforeEach(() => {
  auth.isLoaded = true;
  auth.isSignedIn = false;
});

describe("landing page", () => {
  it("renders the product, all feature groups, install steps, and honest footer", () => {
    render(<HomePage />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Your AI.Your PC.Connected.");
    expect(screen.getByText(/Bring your own provider key/)).toBeInTheDocument();
    expect(screen.getByText(/Illustrative preview — not a live connection/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download for Windows" })).toHaveAttribute("href", "/download");

    const featureRegion = screen.getByRole("region", { name: "Useful connections.Clear controls." });
    expect(within(featureRegion).getAllByRole("article")).toHaveLength(4);
    expect(within(featureRegion).getByRole("heading", { name: "Stay in control" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Connect your devices" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Choose an AI model" })).toBeInTheDocument();
    expect(screen.getByText("OpenRouter")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Smart camera access" })).toBeInTheDocument();
    expect(screen.getByRole("list").querySelectorAll("li")).toHaveLength(4);
    expect(screen.getByRole("heading", { name: "Built by Hammad,open to feedback." })).toBeInTheDocument();
    expect(screen.getByText(/© \d{4} J\.A\.R\.V\.I\.S\./)).toBeInTheDocument();
    expect(screen.queryByText(/Trusted by|50,000|4\.8|No tracking|No selling/i)).not.toBeInTheDocument();
  });

  it("switches the document theme and persists the selection", async () => {
    render(<HomePage />);
    const toggle = await screen.findByRole("button", { name: "Switch to dark theme" });

    fireEvent.click(toggle);

    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(window.localStorage.getItem("jarvis-theme")).toBe("dark");
    expect(screen.getByRole("button", { name: "Switch to light theme" })).toBeInTheDocument();
  });

  it("opens Clerk sign-in for a signed-out Try JARVIS action and redirects after sign-in", () => {
    render(<HomePage />);
    fireEvent.click(screen.getByRole("button", { name: "Try JARVIS" }));

    expect(clerk.openSignIn).toHaveBeenCalledWith({ forceRedirectUrl: "/app" });
  });

  it("sends signed-in users directly to the dashboard", () => {
    auth.isSignedIn = true;
    render(<HomePage />);
    fireEvent.click(screen.getByRole("button", { name: "Try JARVIS" }));

    expect(router.push).toHaveBeenCalledWith("/app");
    expect(clerk.openSignIn).not.toHaveBeenCalled();
  });

  it("opens Clerk sign-up and returns successful sign-up to the dashboard", () => {
    render(<HomePage />);
    fireEvent.click(screen.getAllByRole("button", { name: "Sign Up" })[0]);

    expect(clerk.openSignUp).toHaveBeenCalledWith({ forceRedirectUrl: "/app" });
  });
});
