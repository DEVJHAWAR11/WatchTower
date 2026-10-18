import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Watchtower",
    short_name: "Watchtower",
    description: "AI agents that watch the web for you.",
    start_url: "/dashboard",
    display: "standalone",
    background_color: "#0f1210",
    theme_color: "#0f1210",
    icons: [{ src: "/icon.svg", sizes: "any", type: "image/svg+xml" }],
  };
}
