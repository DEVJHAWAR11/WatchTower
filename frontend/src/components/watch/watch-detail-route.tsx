"use client";

import { use } from "react";

import { WatchDetail } from "./watch-detail";

export function WatchDetailRoute({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <WatchDetail id={id} />;
}
