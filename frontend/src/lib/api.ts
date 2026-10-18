"use client";

import type { ApiErrorBody } from "./types";

export class ApiError extends Error {
  status: number;
  code: string;
  details?: unknown;
  requestId?: string;
  retryAfter?: number;

  constructor(status: number, body: Partial<ApiErrorBody["error"]>, headers?: Headers) {
    super(body.message || "Something went wrong");
    this.status = status;
    this.code = body.code || (status >= 500 ? "server_error" : "error");
    this.details = body.details;
    this.requestId = body.request_id || headers?.get("x-request-id") || undefined;
    const ra = headers?.get("retry-after");
    if (ra) this.retryAfter = Number(ra);
  }

  get isAuth() {
    return this.status === 401;
  }
  get isQuota() {
    return this.code === "quota_exceeded" || this.status === 402;
  }
}

type Json = Record<string, unknown> | unknown[];

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: Json;
  query?: Record<string, string | number | boolean | null | undefined | string[]>;
  idempotencyKey?: string;
  signal?: AbortSignal;
}

function buildQuery(query: RequestOptions["query"]): string {
  if (!query) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => p.append(k, x));
    else p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn;
}

/** Calls the same-origin gateway (/v1/*), which attaches the session from httpOnly cookies. */
export async function api<T = unknown>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method || (opts.body ? "POST" : "GET");
  const headers: Record<string, string> = { accept: "application/json" };
  if (method !== "GET") headers["x-wt-csrf"] = "1";
  if (opts.body !== undefined) headers["content-type"] = "application/json";
  if (opts.idempotencyKey) headers["idempotency-key"] = opts.idempotencyKey;

  let res: Response;
  try {
    res = await fetch(`/v1/${path.replace(/^\//, "")}${buildQuery(opts.query)}`, {
      method,
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      credentials: "same-origin",
      signal: opts.signal,
    });
  } catch (e) {
    if ((e as Error)?.name === "AbortError") throw e;
    throw new ApiError(0, { code: "network", message: "You appear to be offline. Check your connection." });
  }

  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { error: { message: text.slice(0, 200) } };
    }
  }
  if (!res.ok) {
    const err = new ApiError(res.status, (data as ApiErrorBody)?.error || {}, res.headers);
    if (err.isAuth && onUnauthorized && !path.startsWith("auth/")) onUnauthorized();
    throw err;
  }
  return data as T;
}

export function newIdempotencyKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** Human message for any thrown value, with the request id when the API gave one. */
export function errorMessage(e: unknown, fallback = "Something went wrong. Please try again."): string {
  if (e instanceof ApiError) {
    if (e.code === "rate_limited" && e.retryAfter) return `${e.message}`;
    return e.message || fallback;
  }
  if (e instanceof Error && e.message) return e.message;
  return fallback;
}
