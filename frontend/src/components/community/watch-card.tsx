"use client";

import { ArrowRight, Check, TrendingUp, Users, Zap } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { CategoryArt, CategoryIcon, categoryOf } from "@/components/art/category";
import { Button } from "@/components/ui/button";
import { ApiError, errorMessage } from "@/lib/api";
import { useSubscribe } from "@/lib/queries";
import type { PublicWatch } from "@/lib/types";
import { useSignedIn } from "@/lib/use-session";
import { cn, compactNumber, relativeTime } from "@/lib/utils";

export function SubscribeButton({
  watch,
  subscribed,
  className,
  variant = "primary",
  size = "sm",
  full,
}: {
  watch: { id: string; slug: string; title: string };
  subscribed?: boolean;
  className?: string;
  variant?: "primary" | "amber";
  size?: "sm" | "md";
  full?: boolean;
}) {
  const signedIn = useSignedIn();
  const router = useRouter();
  const sub = useSubscribe();
  const go = () => {
    if (!signedIn) {
      router.push(`/signup?next=${encodeURIComponent(`/explore/${watch.slug}`)}`);
      return;
    }
    sub.mutate(
      { id: watch.id, subscribe: !subscribed },
      {
        onSuccess: () =>
          toast.success(subscribed ? "Unsubscribed" : `Subscribed to ${watch.title}`, {
            description: subscribed ? undefined : "You'll be alerted on your default channels.",
          }),
        onError: (e) => {
          if (e instanceof ApiError && e.isQuota) {
            toast.error("Subscription limit reached", { description: e.message, action: { label: "Upgrade", onClick: () => router.push("/settings?tab=plan") } });
          } else toast.error(errorMessage(e));
        },
      },
    );
  };
  return (
    <Button
      onClick={go}
      loading={sub.isPending}
      size={size}
      variant={subscribed ? "subtle" : variant}
      mono
      className={cn(full && "w-full", className)}
      aria-pressed={subscribed}
    >
      {subscribed ? (
        <>
          <Check className="h-3.5 w-3.5" /> Subscribed
        </>
      ) : (
        <>
          Subscribe <ArrowRight className="h-3.5 w-3.5" />
        </>
      )}
    </Button>
  );
}

export function WatchCard({
  watch,
  trending,
  subscribed,
  layout = "feature",
  hrefBase = "/explore",
}: {
  watch: PublicWatch;
  trending?: boolean;
  subscribed?: boolean;
  layout?: "feature" | "compact";
  hrefBase?: string;
}) {
  const cat = categoryOf(watch.category_slug, watch.kind);
  const href = `${hrefBase}/${watch.slug}`;
  const owner = watch.owner?.is_community ? "Watchtower Community" : watch.owner?.handle ? `@${watch.owner.handle}` : watch.owner?.display_name;
  return (
    <article
      className={cn(
        "ticked group relative flex flex-col border bg-elevated/70 p-5 transition-[border-color,box-shadow,transform] duration-300 hover:-translate-y-0.5 hover:shadow-card",
        trending ? "border-amber/70 bg-amber-soft/40" : "border-line hover:border-line-strong",
      )}
    >
      {trending && (
        <span className="label-mono absolute right-4 top-4 z-10 inline-flex items-center gap-1.5 bg-amber px-2 py-1 text-[10px] text-on-amber">
          <TrendingUp className="h-3 w-3" aria-hidden /> Trending
        </span>
      )}
      <div className="flex gap-4">
        <div className="min-w-0 flex-1">
          <div className="label-mono flex items-center gap-2 text-[10.5px] text-ink-2">
            <CategoryIcon slug={watch.category_slug} kind={watch.kind} className="h-4 w-4" />
            {cat.label}
          </div>
          <h3 className="mt-3 font-display text-[23px] leading-[1.1] text-ink">
            <Link href={href} className="after:absolute after:inset-0 focus-visible:outline-none">
              {watch.title}
            </Link>
          </h3>
          {watch.description && <p className="mt-2 line-clamp-2 text-[14px] leading-snug text-ink-2">{watch.description}</p>}
        </div>
        {layout === "feature" && (
          <CategoryArt slug={watch.category_slug} kind={watch.kind} seed={watch.id} className="hidden h-[92px] w-[92px] shrink-0 border border-line grayscale sm:block" />
        )}
      </div>
      <div className="mt-auto pt-5">
        <div className="flex items-center gap-4 border-t border-line pt-4 text-[13px]">
          <span className="flex items-center gap-2 text-ink">
            <Users className="h-4 w-4 text-ink-3" aria-hidden />
            <span>
              <strong className="font-medium">{compactNumber(watch.subscriber_count)}</strong>
              <span className="block text-[11px] text-ink-3">subscribers</span>
            </span>
          </span>
          <span className="h-7 w-px bg-line" aria-hidden />
          <span className="flex items-center gap-2 text-ink-2">
            <Zap className="h-4 w-4 text-ink-3" aria-hidden />
            <span className="leading-tight">
              <span className="block text-[11px] text-ink-3">Last fired</span>
              {watch.last_alert_at ? relativeTime(watch.last_alert_at) : "Not yet"}
            </span>
          </span>
          <span className="ml-auto text-right leading-tight text-ink-2">
            <span className="block text-[11px] text-ink-3">Alerts</span>
            {compactNumber(watch.alert_count)}
          </span>
        </div>
        <div className="relative z-10 mt-4 flex items-center justify-between gap-3">
          {owner && <span className="truncate text-[12px] text-ink-3">by {owner}</span>}
          <SubscribeButton watch={watch} subscribed={subscribed} variant={trending ? "amber" : "primary"} className="ml-auto" />
        </div>
      </div>
    </article>
  );
}

export function WatchCardSkeleton() {
  return (
    <div className="ticked flex h-[236px] flex-col border border-line bg-elevated/50 p-5">
      <div className="skeleton h-3 w-20" />
      <div className="skeleton mt-4 h-6 w-3/4" />
      <div className="skeleton mt-3 h-4 w-full" />
      <div className="skeleton mt-2 h-4 w-2/3" />
      <div className="mt-auto flex justify-between">
        <div className="skeleton h-8 w-24" />
        <div className="skeleton h-8 w-24" />
      </div>
    </div>
  );
}
