import "server-only";

import { cacheLife } from "next/cache";

import type { Category, Collection, ExplorePage, Plan, PublicWatchDetail } from "@/lib/types";

import { backendUrl } from "./session";

/** Public, cacheable reads for server-rendered (SEO) pages. They degrade to null if the API is unreachable. */
async function getJson<T>(path: string): Promise<T | null> {
  try {
    const r = await fetch(`${backendUrl()}/v1/${path}`, { headers: { accept: "application/json" } });
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

export async function getPlans() {
  "use cache";
  cacheLife("hours");
  return getJson<Plan[]>("plans");
}

export async function getExplore(sort = "trending", category = "", q = "", limit = 24) {
  "use cache";
  cacheLife("minutes");
  const p = new URLSearchParams({ sort, limit: String(limit) });
  if (category) p.set("category", category);
  if (q) p.set("q", q);
  return getJson<ExplorePage>(`explore?${p}`);
}

export async function getCategories() {
  "use cache";
  cacheLife("hours");
  return getJson<Category[]>("explore/categories");
}

export async function getCollections() {
  "use cache";
  cacheLife("minutes");
  return getJson<Collection[]>("explore/collections");
}

export async function getPublicWatch(slug: string) {
  "use cache";
  cacheLife("minutes");
  return getJson<PublicWatchDetail>(`explore/watches/${encodeURIComponent(slug)}`);
}
