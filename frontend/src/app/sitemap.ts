import type { MetadataRoute } from "next";

import { getExplore } from "@/lib/server/public-api";

const site = (process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000").replace(/\/$/, "");

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const pages: MetadataRoute.Sitemap = ["", "/explore", "/pricing", "/docs", "/privacy", "/terms", "/signup"].map((p) => ({
    url: `${site}${p}`,
    changeFrequency: p === "/explore" ? "hourly" : "weekly",
    priority: p === "" ? 1 : 0.6,
  }));
  const popular = await getExplore("popular", "", "", 50);
  for (const w of popular?.items ?? []) {
    pages.push({ url: `${site}/explore/${w.slug}`, changeFrequency: "daily", priority: 0.5 });
  }
  return pages;
}
