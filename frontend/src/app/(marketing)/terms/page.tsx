import type { Metadata } from "next";

import { Prose } from "@/components/marketing/prose";

export const metadata: Metadata = {
  title: "Terms",
  description: "The rules for using Watchtower.",
  alternates: { canonical: "/terms" },
};

export default function TermsPage() {
  return (
    <Prose title="Terms of use" kicker="/ Legal" updated="18 Oct 2026">
      <p>By using Watchtower you agree to these terms. They are short on purpose.</p>
      <h2>Acceptable use</h2>
      <ul>
        <li>Watch public information only. Don&apos;t use Watchtower to track, profile or harass private individuals.</li>
        <li>Don&apos;t publish scams, spam, adult content or anything illegal as a community watch.</li>
        <li>
          Don&apos;t try to overload the sites we check or our service. We respect robots.txt and rate-limit every
          domain.
        </li>
      </ul>
      <h2>Alerts are best effort</h2>
      <p>
        We work hard to catch changes quickly and accurately, but websites change, go down or block automated visitors.
        Always confirm important information (exam dates, deadlines, prices) on the official source before acting.
      </p>
      <h2>Community watches</h2>
      <p>
        When you make a watch public you allow others to subscribe to it and fork it. Public watches are moderated and
        may be unlisted or removed.
      </p>
      <h2>Plans</h2>
      <p>
        Plan limits are shown on the pricing page and in your settings. We may change prices with notice; changes never
        apply to a period you&apos;ve already paid for.
      </p>
      <h2>Ending your account</h2>
      <p>You can delete your account at any time from settings. We may suspend accounts that break these terms.</p>
    </Prose>
  );
}
