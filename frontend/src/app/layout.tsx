import type { Metadata, Viewport } from "next";
import { Martian_Mono, Newsreader, Schibsted_Grotesk } from "next/font/google";

import { Providers } from "@/components/providers";

import "./globals.css";

const display = Newsreader({
  subsets: ["latin"],
  variable: "--font-newsreader",
  axes: ["opsz"],
  style: ["normal", "italic"],
  display: "swap",
});
const sans = Schibsted_Grotesk({ subsets: ["latin"], variable: "--font-grotesk", display: "swap" });
const mono = Martian_Mono({ subsets: ["latin"], variable: "--font-martian", axes: ["wdth"], display: "swap" });

const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: { default: "Watchtower: AI agents that watch the web for you", template: "%s · Watchtower" },
  description:
    "Describe what to watch in plain English. Watchtower's AI agents check the web on a schedule, judge what really changed, do the follow-up work and alert you by email, push or Telegram.",
  applicationName: "Watchtower",
  keywords: ["website change monitoring", "exam result alerts", "job alerts", "price drop alerts", "AI agents", "India"],
  openGraph: {
    type: "website",
    siteName: "Watchtower",
    title: "Watchtower: the web moves, we keep watch",
    description: "AI agents monitor the sources that matter and bring you the signal, before you have to look.",
    url: siteUrl,
    locale: "en_IN",
  },
  twitter: { card: "summary_large_image" },
  alternates: { canonical: "/" },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f0ece2" },
    { media: "(prefers-color-scheme: dark)", color: "#0f1210" },
  ],
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en-IN" suppressHydrationWarning className={`${display.variable} ${sans.variable} ${mono.variable}`}>
      <body className="min-h-dvh">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:bg-ink focus:px-4 focus:py-2 focus:text-bg"
        >
          Skip to content
        </a>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
