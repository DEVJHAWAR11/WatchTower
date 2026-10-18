"use client";

import { useSyncExternalStore } from "react";

function read(): boolean {
  return typeof document !== "undefined" && /(?:^|;\s*)wt_s=1/.test(document.cookie);
}

/** Whether a session cookie hint is present (null during SSR/hydration). Holds no secret. */
export function useSignedIn(): boolean | null {
  return useSyncExternalStore(
    (cb) => {
      window.addEventListener("focus", cb);
      return () => window.removeEventListener("focus", cb);
    },
    read,
    () => null,
  );
}
