import { z } from "zod";

/**
 * Auth API client — typed mirrors of the FastAPI schemas in
 * `backend/src/bibliohack/identity/interfaces/http/schemas.py`.
 *
 * Sessions ride an httpOnly cookie set by the backend on login, so every
 * call here uses `credentials: "include"`: a no-op same-origin in
 * production (cookies are sent anyway) but required in dev, where the
 * Astro dev server and the API live on different localhost ports.
 *
 * Endpoints mirrored:
 *   POST /api/auth/register                 → 201 | 4xx
 *   POST /api/auth/verify                   → 204 | 400
 *   POST /api/auth/login                    → User (sets cookie) | 4xx
 *   POST /api/auth/logout                   → 204
 *   GET  /api/auth/me                       → User | 401
 *   POST /api/auth/password/reset-request   → 202 (always)
 *   POST /api/auth/password/reset           → 204 | 4xx
 */

// ── Schemas ──────────────────────────────────────────────────────────

export const UserSchema = z.object({
  id: z.string(),
  email: z.string(),
  display_name: z.string().nullable().optional(),
  email_verified: z.boolean(),
  created_at: z.string(),
});
export type User = z.infer<typeof UserSchema>;

// ── Errors ───────────────────────────────────────────────────────────

/**
 * Thrown on recognised non-2xx responses. `detail` carries the backend's
 * stable error codes ("email_taken", "invalid_credentials",
 * "email_not_verified", …) so forms can branch without string-matching
 * prose.
 */
export class AuthApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(`Auth API ${status}: ${detail}`);
    this.name = "AuthApiError";
  }
}

// ── Endpoints ────────────────────────────────────────────────────────

export interface RegisterParams {
  email: string;
  password: string;
  // `| undefined` spelled out: tsconfig has exactOptionalPropertyTypes on.
  displayName?: string | undefined;
  turnstileToken?: string | undefined;
}

/** `POST /api/auth/register` — creates an unverified account and mails the link. */
export async function register(apiBaseUrl: string, params: RegisterParams): Promise<void> {
  await requestJson(apiBaseUrl, "/api/auth/register", {
    email: params.email,
    password: params.password,
    display_name: params.displayName ?? null,
    turnstile_token: params.turnstileToken ?? null,
  });
}

/** `POST /api/auth/verify` — consumes the emailed verification token. */
export async function verifyEmail(apiBaseUrl: string, token: string): Promise<void> {
  await requestJson(apiBaseUrl, "/api/auth/verify", { token });
}

export interface LoginParams {
  email: string;
  password: string;
  turnstileToken?: string | undefined;
}

/** `POST /api/auth/login` — opens the session (httpOnly cookie) and returns the user. */
export async function login(apiBaseUrl: string, params: LoginParams): Promise<User> {
  const response = await requestJson(apiBaseUrl, "/api/auth/login", {
    email: params.email,
    password: params.password,
    turnstile_token: params.turnstileToken ?? null,
  });
  const json: unknown = await response.json();
  return UserSchema.parse(json);
}

/** `POST /api/auth/logout` — kills the session server-side. Idempotent. */
export async function logout(apiBaseUrl: string): Promise<void> {
  await requestJson(apiBaseUrl, "/api/auth/logout", {});
}

/**
 * `GET /api/auth/me` — the authenticated user, or `null` when there is no
 * (valid) session. 401 is an expected state here, not an error.
 */
export async function fetchCurrentUser(
  apiBaseUrl: string,
  signal?: AbortSignal,
): Promise<User | null> {
  const response = await fetch(new URL("/api/auth/me", apiBaseUrl).toString(), {
    headers: { Accept: "application/json" },
    credentials: "include",
    ...(signal ? { signal } : {}),
  });
  if (response.status === 401) return null;
  if (!response.ok) {
    throw new AuthApiError(response.status, await readDetail(response));
  }
  const json: unknown = await response.json();
  return UserSchema.parse(json);
}

/** `POST /api/auth/password/reset-request` — always 202 (no account enumeration). */
export async function requestPasswordReset(apiBaseUrl: string, email: string): Promise<void> {
  await requestJson(apiBaseUrl, "/api/auth/password/reset-request", { email });
}

/** `POST /api/auth/password/reset` — redeems the emailed token; revokes all sessions. */
export async function resetPassword(
  apiBaseUrl: string,
  token: string,
  newPassword: string,
): Promise<void> {
  await requestJson(apiBaseUrl, "/api/auth/password/reset", {
    token,
    new_password: newPassword,
  });
}

// ── Account self-service (GDPR) ──────────────────────────────────────

/** `GET /api/account/export` — everything the server holds, as a JSON blob. */
export async function exportAccountData(apiBaseUrl: string): Promise<Blob> {
  const response = await fetch(new URL("/api/account/export", apiBaseUrl).toString(), {
    headers: { Accept: "application/json" },
    credentials: "include",
  });
  if (!response.ok) {
    throw new AuthApiError(response.status, await readDetail(response));
  }
  return response.blob();
}

/** `DELETE /api/account` — erases the account; requires the password again. */
export async function deleteAccount(apiBaseUrl: string, password: string): Promise<void> {
  const response = await fetch(new URL("/api/account", apiBaseUrl).toString(), {
    method: "DELETE",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    credentials: "include",
    body: JSON.stringify({ password }),
  });
  if (!response.ok) {
    throw new AuthApiError(response.status, await readDetail(response));
  }
}

// ── helpers ──────────────────────────────────────────────────────────

async function requestJson(
  apiBaseUrl: string,
  path: string,
  body: Record<string, unknown>,
): Promise<Response> {
  const response = await fetch(new URL(path, apiBaseUrl).toString(), {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new AuthApiError(response.status, await readDetail(response));
  }
  return response;
}

async function readDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (
      typeof body === "object" &&
      body !== null &&
      "detail" in body &&
      typeof (body as { detail: unknown }).detail === "string"
    ) {
      return (body as { detail: string }).detail;
    }
  } catch {
    /* response wasn't JSON — fall through to the status text */
  }
  return response.statusText || `HTTP ${response.status}`;
}
