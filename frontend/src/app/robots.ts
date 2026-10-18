import type { MetadataRoute } from "next";

const site = (process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000").replace(/\/$/, "");

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: ["/", "/explore", "/pricing", "/docs"],
        disallow: ["/v1/", "/api/", "/dashboard", "/watches", "/alerts", "/community", "/settings", "/admin", "/auth/"],
      },
    ],
    sitemap: `${site}/sitemap.xml`,
  };
}
