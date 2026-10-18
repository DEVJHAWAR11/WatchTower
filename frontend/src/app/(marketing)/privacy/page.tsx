import type { Metadata } from "next";

import { Prose } from "@/components/marketing/prose";

export const metadata: Metadata = {
  title: "Privacy",
  description: "What Watchtower stores, why, and how to export or delete it.",
  alternates: { canonical: "/privacy" },
};

export default function PrivacyPage() {
  return (
    <Prose title="Privacy" kicker="/ Legal" updated="18 Oct 2026">
      <p>
        Watchtower watches public web pages on your behalf. This page explains what we keep about you and why. We built
        it to collect as little as possible.
      </p>
      <h2>What we store</h2>
      <ul>
        <li>
          <strong>Account:</strong> your email address, display name, optional handle, time zone and notification
          preferences. Passwords are handled by our identity provider (Supabase Auth) and never touch our database.
        </li>
        <li>
          <strong>Watches:</strong> what you asked us to watch, the pages we check, versions of each watch, check
          results and alerts.
        </li>
        <li>
          <strong>Delivery details:</strong> push subscription endpoints, your linked Telegram chat and any webhook
          URLs you add (webhook secrets are encrypted).
        </li>
        <li>
          <strong>Feedback:</strong> the 👍/👎 you give alerts, used only to tune that watch.
        </li>
      </ul>
      <h2>What we don&apos;t do</h2>
      <ul>
        <li>We don&apos;t sell or rent your data, and we don&apos;t show ads.</li>
        <li>We don&apos;t log in to sites as you or read private accounts.</li>
        <li>We don&apos;t watch private individuals. Requests to track people are refused.</li>
      </ul>
      <h2>AI processing</h2>
      <p>
        Page excerpts and your watch condition are sent to our AI provider to decide whether a change matters and to
        summarise alerts. Unchanged pages are never sent. Your email and personal details are not included in those
        requests.
      </p>
      <h2>Your rights</h2>
      <p>
        Under India&apos;s Digital Personal Data Protection Act and similar laws you can access, correct, export and
        delete your data. Use <em>Settings → Data &amp; privacy</em> to download a full export or permanently delete
        your account. Public watches that others subscribe to are handed to the Watchtower Community account instead of
        being deleted.
      </p>
      <h2>Retention</h2>
      <p>Check history is kept for your plan&apos;s retention period (30 days on Free) and then deleted automatically.</p>
      <h2>Contact</h2>
      <p>Questions about privacy? Reply to any Watchtower email and it reaches a person.</p>
    </Prose>
  );
}
