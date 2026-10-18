import { ArrowLeft, ExternalLink, Users, Zap } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { CategoryArt, CategoryIcon, categoryOf } from "@/components/art/category";
import { Topo } from "@/components/art/topo";
import { PublicWatchActions } from "@/components/community/public-watch-actions";
import { Badge, Card, SectionLabel, Skeleton } from "@/components/ui/display";
import { getPublicWatch } from "@/lib/server/public-api";
import { compactNumber, formatDate, formatDateTime, hostOf } from "@/lib/utils";

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const w = await getPublicWatch(slug);
  if (!w) return { title: "Watch not found", robots: { index: false } };
  const cat = categoryOf(w.category_slug, w.kind).label;
  return {
    title: `${w.title} alerts`,
    description: w.description || `Get alerted the moment ${w.title} changes. A free ${cat.toLowerCase()} watch on Watchtower.`,
    alternates: { canonical: `/explore/${w.slug}` },
    openGraph: { title: `${w.title} · Watchtower`, description: w.description || undefined, type: "article" },
  };
}

export default function PublicWatchPage({ params }: Props) {
  return (
    <div className="relative">
      <Topo className="h-[480px]" />
      <div className="relative mx-auto max-w-[1180px] px-4 pb-24 pt-10 sm:px-8">
        <Link href="/explore" className="inline-flex items-center gap-2 text-sm text-ink-2 hover:text-ink">
          <ArrowLeft className="h-4 w-4" /> All community watches
        </Link>
        <Suspense fallback={<DetailSkeleton />}>
          <Detail params={params} />
        </Suspense>
      </div>
    </div>
  );
}

async function Detail({ params }: Props) {
  const { slug } = await params;
  const w = await getPublicWatch(slug);
  if (!w) notFound();
  const cat = categoryOf(w.category_slug, w.kind);
  const owner = w.owner?.is_community ? "Watchtower Community" : w.owner?.handle ? `@${w.owner.handle}` : w.owner?.display_name || "a community member";

  return (
    <>
      <div className="mt-8 grid gap-10 lg:grid-cols-[1fr_300px]">
        <div>
          <div className="label-mono flex items-center gap-2 text-ink-2">
            <CategoryIcon slug={w.category_slug} kind={w.kind} className="h-4 w-4" /> {cat.label}
          </div>
          <h1 className="mt-4 font-display text-[clamp(2.4rem,5vw,4.2rem)] leading-[0.98] text-ink">{w.title}</h1>
          {w.description && <p className="mt-5 max-w-2xl text-lg leading-relaxed text-ink-2">{w.description}</p>}
          <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-3 text-[15px] text-ink-2">
            <span className="flex items-center gap-2">
              <Users className="h-4 w-4 text-ink-3" aria-hidden /> {compactNumber(w.subscriber_count)} subscribers
            </span>
            <span className="flex items-center gap-2">
              <Zap className="h-4 w-4 text-ink-3" aria-hidden /> {w.alert_count} alerts sent
            </span>
            <span>Created {formatDate(w.created_at)} by {owner}</span>
            {w.status !== "active" && <Badge tone="amber">{w.status}</Badge>}
          </div>
          {w.tags?.length > 0 && (
            <div className="mt-5 flex flex-wrap gap-2">
              {w.tags.map((t) => (
                <Badge key={t}>{t}</Badge>
              ))}
            </div>
          )}
          <div className="mt-8">
            <PublicWatchActions watch={w} />
          </div>
        </div>
        <CategoryArt slug={w.category_slug} kind={w.kind} seed={w.id} className="hidden aspect-square w-full border border-line grayscale lg:block" />
      </div>

      <section className="mt-16" aria-labelledby="recent-title">
        <SectionLabel index={1} as="h2">
          <span id="recent-title">Recent alerts</span>
        </SectionLabel>
        {w.recent_alerts.length === 0 ? (
          <Card className="mt-5 p-8 text-center">
            <p className="font-display text-2xl text-ink">Quiet so far.</p>
            <p className="mt-2 text-sm text-ink-2">This watch hasn&apos;t fired yet. Subscribe and you&apos;ll hear the moment it does.</p>
          </Card>
        ) : (
          <ol className="mt-5 space-y-4">
            {w.recent_alerts.map((a) => (
              <li key={a.id}>
                <Card className="relative p-5 sm:p-6">
                  <span className="absolute inset-y-5 left-0 w-[3px] bg-amber" aria-hidden />
                  <div className="label-mono text-ink-3">{formatDateTime(a.created_at)}</div>
                  <h3 className="mt-2 font-display text-2xl leading-tight text-ink">{a.title}</h3>
                  <p className="mt-2 text-[15px] text-ink-2">{a.summary}</p>
                  <a href={a.source_url} target="_blank" rel="noopener noreferrer nofollow" className="mt-3 inline-flex items-center gap-1.5 text-sm text-ink underline underline-offset-4">
                    Source · {hostOf(a.source_url)} <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                </Card>
              </li>
            ))}
          </ol>
        )}
      </section>
    </>
  );
}

function DetailSkeleton() {
  return (
    <div className="mt-8 space-y-5">
      <Skeleton className="h-4 w-24" />
      <Skeleton className="h-14 w-3/4" />
      <Skeleton className="h-5 w-1/2" />
      <Skeleton className="h-10 w-40" />
    </div>
  );
}
