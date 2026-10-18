import { Topo } from "@/components/art/topo";
import { SectionLabel } from "@/components/ui/display";

export function Prose({ title, kicker, updated, children }: { title: string; kicker: string; updated?: string; children: React.ReactNode }) {
  return (
    <div className="relative">
      <Topo className="h-[420px]" />
      <article className="relative mx-auto max-w-[760px] px-4 pb-24 pt-14 sm:px-8">
        <SectionLabel>{kicker}</SectionLabel>
        <h1 className="mt-6 font-display text-[clamp(2.6rem,6vw,4.6rem)] leading-[0.95] text-ink">{title}</h1>
        {updated && <p className="label-mono mt-4 text-ink-3">Last updated {updated}</p>}
        <div className="prose-wt mt-10">{children}</div>
      </article>
    </div>
  );
}
