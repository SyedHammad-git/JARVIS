import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "J.A.R.V.I.S. Dashboard",
    short_name: "JARVIS",
    description: "Control your paired Windows PC from your phone.",
    start_url: "/app",
    display: "standalone",
    background_color: "#07111f",
    theme_color: "#07111f",
    icons: [
      { src: "/icons/jarvis-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/jarvis-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/jarvis-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
