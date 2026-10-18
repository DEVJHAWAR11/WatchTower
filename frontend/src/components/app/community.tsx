"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { use } from "react";

import { ExploreBrowser } from "@/components/community/explore-browser";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, Kicker } from "@/components/ui/display";
import { PageLoader } from "@/components/ui/spinner";
import { WatchDetail } from "@/components/watch/watch-detail";
import { ApiError, api } from "@/lib/api";
import type { PublicWatchDetail } from "@/lib/types";

import { PageFrame } from "./app-shell";

export function CommunityPage() {
  return (
    <PageFrame>
      <div className="flex items-start justify-between gap-6">
        <div>
          <div className="label-mono text-ink-3">/ Community</div>
          <h1 className="mt-4 font-display text-[clamp(2.4rem,5vw,4.4rem)] leading-[0.96] text-ink">
            Watches for a more
            <br />
            informed <em className="accent">you.</em>
          </h1>
          <p className="mt-4 max-w-2xl text-[16px] text-ink-2">Explore watches created by the community. Follow, customise, or create your own.</p>
        </div>
        <Kicker className="hidden text-right lg:block" lines={["// discover", "// follow", "// stay informed", "// together"]} />
      </div>
      <div className="mt-10">
        <ExploreBrowser hrefBase="/community" />
      </div>
    </PageFrame>
  );
}

export function CommunityWatchRoute({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const q = useQuery({ queryKey: ["explore", "watch", slug], queryFn: () => api<PublicWatchDetail>(`explore/watches/${encodeURIComponent(slug)}`) });
  if (q.isPending) return <PageLoader />;
  if (q.isError)
    return (
      <PageFrame>
        {q.error instanceof ApiError && [404, 422].includes(q.error.status) ? (
          <EmptyState title="Watch not found" body="It may have been unlisted or removed." action={<Button asChild><Link href="/community">Back to community</Link></Button>} />
        ) : (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        )}
      </PageFrame>
    );
  return <WatchDetail id={q.data.id} />;
}
