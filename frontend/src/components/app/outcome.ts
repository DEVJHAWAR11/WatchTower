import type { DotTone } from "@/components/ui/display";
import type { RunOutcome, WatchStatus } from "@/lib/types";

/** Plain-language labels for check outcomes and who decided them. */
export const OUTCOME_LABEL: Record<RunOutcome, string> = {
  baseline: "First snapshot taken",
  skipped_unchanged: "No changes",
  no_match: "Changed, not relevant",
  matched: "Condition met",
  duplicate: "Already alerted",
  deferred: "Deferred (AI busy)",
  blocked: "Source blocked us",
  error: "Source error",
};

export const DECIDED_BY_LABEL: Record<string, string> = {
  hash: "Page unchanged: AI skipped",
  noise: "Only noise changed: AI skipped",
  rule: "Decided by rules: AI skipped",
  triage: "Quick AI triage",
  llm: "AI judged the change",
  cache: "Reused an earlier verdict",
  none: "No decision needed",
};

export function outcomeTone(o: RunOutcome | null | undefined): DotTone {
  switch (o) {
    case "matched":
      return "amber";
    case "error":
    case "blocked":
      return "err";
    case "no_match":
    case "duplicate":
      return "ok";
    case "deferred":
      return "info";
    default:
      return "idle";
  }
}

export function watchTone(status: WatchStatus, lastOutcome?: RunOutcome | null, alerts24h = 0): DotTone {
  if (status === "error" || lastOutcome === "error" || lastOutcome === "blocked") return "err";
  if (status === "paused" || status === "completed" || status === "expired" || status === "archived") return "idle";
  if (alerts24h > 0 || lastOutcome === "matched") return "amber";
  return "ok";
}

export const STATUS_LABEL: Record<string, string> = {
  active: "Active",
  paused: "Paused",
  error: "Needs attention",
  completed: "Completed",
  expired: "Expired",
  archived: "Archived",
  draft: "Draft",
};

export const NODE_LABEL: Record<string, string> = {
  fetch: "Fetching sources",
  extract: "Reading the page",
  change_gate: "Comparing with last snapshot",
  rules: "Checking rules",
  triage: "Quick relevance check",
  judge: "AI judging the change",
  verify: "Verifying evidence",
  dedup: "Checking for duplicates",
  fire: "Firing alert",
  act: "Doing follow-up work",
  notify: "Sending notifications",
};
