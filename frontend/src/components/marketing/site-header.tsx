"use client";

import { ArrowUpRight, Menu, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { Logo } from "@/components/art/logo";
import { ThemeFlip, ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { useSignedIn } from "@/lib/use-session";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/#how-it-works", label: "How it works" },
  { href: "/explore", label: "Community" },
  { href: "/pricing", label: "Pricing" },
  { href: "/docs", label: "Docs" },
];

export function SiteHeader() {
  const signedIn = useSignedIn();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 8);
    on();
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);
  const [lastPath, setLastPath] = useState(pathname);
  if (lastPath !== pathname) {
    setLastPath(pathname);
    setOpen(false);
  }
  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  return (
    <header
      className={cn(
        "sticky top-0 z-40 border-b transition-[background-color,border-color,backdrop-filter] duration-300",
        scrolled || open ? "border-line bg-bg/85 backdrop-blur-md" : "border-transparent bg-transparent",
      )}
    >
      <div className="mx-auto flex h-[72px] max-w-[1440px] items-center justify-between gap-6 px-4 sm:px-8 lg:px-12">
        <Logo />
        <nav aria-label="Main" className="hidden items-center gap-9 md:flex">
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              className={cn(
                "relative text-[15px] text-ink-2 transition-colors hover:text-ink",
                pathname === n.href && "text-ink after:absolute after:-bottom-1.5 after:left-0 after:h-px after:w-full after:bg-ink",
              )}
            >
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="flex items-center gap-2">
          <ThemeFlip className="hidden sm:grid" />
          {signedIn === true ? (
            <Button asChild mono className="hidden sm:inline-flex">
              <Link href="/dashboard">
                Open dashboard <ArrowUpRight className="h-4 w-4" />
              </Link>
            </Button>
          ) : (
            <>
              <Link href="/login" className="hidden px-3 text-[15px] text-ink-2 hover:text-ink sm:block">
                Sign in
              </Link>
              <Button asChild mono className="hidden sm:inline-flex">
                <Link href="/signup">
                  Start watching <ArrowUpRight className="h-4 w-4" />
                </Link>
              </Button>
            </>
          )}
          <button
            className="grid h-10 w-10 place-items-center rounded-[3px] text-ink md:hidden"
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
            aria-controls="mobile-nav"
            onClick={() => setOpen((o) => !o)}
          >
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>
      <AnimatePresence>
        {open && (
          <motion.nav
            id="mobile-nav"
            aria-label="Mobile"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "calc(100dvh - 72px)" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.25, ease: [0.2, 0.8, 0.2, 1] }}
            className="overflow-hidden border-t border-line bg-bg md:hidden"
          >
            <div className="flex h-full flex-col px-4 pb-8 pt-4">
              {NAV.map((n, i) => (
                <motion.div key={n.href} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 + i * 0.04 }}>
                  <Link href={n.href} className="flex items-center justify-between border-b border-line py-4 font-display text-3xl text-ink">
                    {n.label}
                    <ArrowUpRight className="h-5 w-5 text-ink-3" />
                  </Link>
                </motion.div>
              ))}
              <div className="mt-auto space-y-3">
                <div className="flex items-center justify-between">
                  <span className="label-mono text-ink-3">Theme</span>
                  <ThemeToggle />
                </div>
                {signedIn ? (
                  <Button asChild size="lg" className="w-full">
                    <Link href="/dashboard">Open dashboard</Link>
                  </Button>
                ) : (
                  <>
                    <Button asChild size="lg" className="w-full">
                      <Link href="/signup">Start watching, free</Link>
                    </Button>
                    <Button asChild size="lg" variant="outline" className="w-full">
                      <Link href="/login">Sign in</Link>
                    </Button>
                  </>
                )}
              </div>
            </div>
          </motion.nav>
        )}
      </AnimatePresence>
    </header>
  );
}

/** Static header shown while the interactive one streams in on request-time routes. */
export function SiteHeaderFallback() {
  return (
    <header className="sticky top-0 z-40 border-b border-transparent">
      <div className="mx-auto flex h-[72px] max-w-[1440px] items-center justify-between gap-6 px-4 sm:px-8 lg:px-12">
        <Logo />
        <nav aria-label="Main" className="hidden items-center gap-9 md:flex">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} className="text-[15px] text-ink-2 hover:text-ink">
              {n.label}
            </Link>
          ))}
        </nav>
        <span className="h-10 w-10 md:w-[180px]" />
      </div>
    </header>
  );
}
