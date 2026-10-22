import { CategoryArt } from "@/components/art/category";
import { Logo } from "@/components/art/logo";
import { ObservatoryScene } from "@/components/art/observatory";
import { Radar } from "@/components/art/radar";
import { Topo } from "@/components/art/topo";
import { ThemeFlip } from "@/components/theme-toggle";
import { Coordinates, Crosshair, Kicker, SectionLabel } from "@/components/ui/display";

export function AuthShell({ index, kicker, title, accent, intro, children }: {
  index: string;
  kicker: string;
  title: React.ReactNode;
  accent: React.ReactNode;
  intro: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="grid grid-cols-1 min-h-dvh lg:grid-cols-[1.08fr_1fr]">
      {/* instrument panel */}
      <aside className="relative hidden h-dvh overflow-hidden border-r border-line lg:sticky lg:top-0 lg:block" aria-hidden>
        <Topo />
        <div className="absolute left-12 top-10 flex w-[calc(100%-6rem)] items-start justify-between">
          <Logo />
          <Kicker lines={["Monitor /", "Analyze /", "Alert /"]} />
        </div>
        <div className="absolute left-12 top-36">
          <SectionLabel index="01">
            The web
            <br />
            never stops
            <br />
            moving.
          </SectionLabel>
          <div className="mt-10 flex flex-col gap-2">
            {["government", "tech-releases", "jobs"].map((c) => (
              <CategoryArt key={c} slug={c} seed={`auth-${c}`} className="h-[74px] w-[74px] border border-line grayscale" />
            ))}
          </div>
          <Kicker className="mt-6" lines={["//global", "//real time", "//always on"]} />
        </div>
        <div className="absolute left-1/2 top-[12%] aspect-square w-[58%] -translate-x-1/2">
          <Radar />
        </div>
        <div className="absolute right-12 top-[44%] text-right">
          <Coordinates />
          <Kicker className="mt-8" lines={["/ sources", "/ changes", "/ insights"]} />
        </div>
        <div className="absolute bottom-0 right-0 h-[46%] w-[72%] [mask-image:linear-gradient(to_bottom,transparent,black_35%),linear-gradient(to_right,transparent,black_30%)] [mask-composite:intersect]">
          <ObservatoryScene parallax={false} />
        </div>
        <div className="absolute bottom-10 left-12 max-w-[62%]">
          <p className="font-display text-[clamp(1.9rem,2.7vw,2.9rem)] leading-[1] text-ink">
            A quieter internet
            <br />
            for a more informed <em className="accent">you.</em>
          </p>
          <div className="mt-5 h-px w-12 bg-ink" />
          <Kicker className="mt-4" lines={["Signals today.", "Better decisions tomorrow."]} />
        </div>
      </aside>

      {/* form */}
      <main id="main" className="relative flex flex-col px-4 py-8 sm:px-10 lg:px-16">
        <div className="flex items-center justify-between lg:justify-end">
          <span className="lg:hidden">
            <Logo />
          </span>
          <div className="flex items-center gap-4">
            <Kicker className="hidden text-right sm:block" lines={["Same web.", "A more", "informed you."]} />
            <ThemeFlip />
          </div>
        </div>
        <div className="mx-auto flex w-full max-w-[460px] flex-1 flex-col justify-center py-10">
          <SectionLabel index={index}>{kicker}</SectionLabel>
          <h1 className="mt-6 font-display text-[clamp(2.6rem,5vw,4rem)] leading-[0.95] text-ink">
            {title}
            <br />
            <em className="accent">{accent}</em>
          </h1>
          <p className="mt-5 text-[16px] text-ink-2">{intro}</p>
          <div className="mt-8">{children}</div>
        </div>
        <div className="flex items-center justify-between">
          <Crosshair size={22} />
          <p className="label-mono text-[10px] text-ink-3">By people who stay curious.</p>
        </div>
      </main>
    </div>
  );
}
