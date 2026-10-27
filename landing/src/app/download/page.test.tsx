import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const releaseUrl = "https://github.com/SyedHammad-git/JARVIS/releases/download/v18.0.0/JARVIS-Device-Client-Setup-18.0.0.exe";
const checksum = "a".repeat(64);

describe("Windows download page", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("NEXT_PUBLIC_DOWNLOAD_URL", releaseUrl);
    vi.stubEnv("NEXT_PUBLIC_DOWNLOAD_VERSION", "18.0.0");
    vi.stubEnv("NEXT_PUBLIC_DOWNLOAD_SHA256", checksum);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllEnvs();
  });

  async function renderPage() {
    const { default: DownloadPage } = await import("./page");
    render(<DownloadPage />);
  }

  it("links only to a GitHub release asset and displays its SHA-256", async () => {
    await renderPage();

    const link = screen.getByRole("link", { name: "Download installer" });
    expect(link).toHaveAttribute("href", releaseUrl);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
    expect(screen.getByText("Version 18.0.0")).toBeInTheDocument();
    expect(screen.getByLabelText("SHA-256 checksum")).toHaveTextContent(checksum);
  });

  it("does not present an invalid URL or malformed checksum as a valid download", async () => {
    vi.stubEnv("NEXT_PUBLIC_DOWNLOAD_URL", "http://downloads.example.test/app.exe");
    vi.stubEnv("NEXT_PUBLIC_DOWNLOAD_SHA256", "not-a-checksum");
    await renderPage();

    expect(screen.getByRole("button", { name: "Coming soon" })).toBeDisabled();
    expect(screen.queryByRole("link", { name: "Download installer" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("alert").map((alert) => alert.textContent)).toEqual(expect.arrayContaining([
      expect.stringContaining("HTTPS GitHub Release asset URL"),
      expect.stringContaining("64 hexadecimal characters"),
    ]));
    expect(screen.getByLabelText("SHA-256 checksum")).toHaveTextContent("Checksum not published yet.");
  });

  it("shows a coming-soon control when no release URL is configured", async () => {
    vi.stubEnv("NEXT_PUBLIC_DOWNLOAD_URL", "");
    vi.stubEnv("NEXT_PUBLIC_DOWNLOAD_SHA256", "");
    await renderPage();

    expect(screen.getByRole("button", { name: "Coming soon" })).toBeDisabled();
    expect(screen.getByLabelText("SHA-256 checksum")).toHaveTextContent("Checksum not published yet.");
  });
});
