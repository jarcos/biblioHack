import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import {
  AuthApiError,
  UserSchema,
  fetchCurrentUser,
  login,
  register,
  resetPassword,
} from "../src/infrastructure/api/auth";

const USER = {
  id: "u-1",
  email: "jose@example.com",
  display_name: "José",
  email_verified: true,
  created_at: "2026-06-10T09:00:00Z",
};

describe("UserSchema", () => {
  it("accepts a well-formed user", () => {
    expect(UserSchema.parse(USER).email).toBe("jose@example.com");
  });

  it("tolerates a missing display_name", () => {
    const { display_name: _omitted, ...rest } = USER;
    expect(UserSchema.parse(rest).display_name).toBeUndefined();
  });

  it("rejects a missing email", () => {
    expect(() => UserSchema.parse({ ...USER, email: undefined })).toThrow();
  });
});

describe("auth client", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function mockFetch(): ReturnType<typeof vi.fn> {
    return globalThis.fetch as ReturnType<typeof vi.fn>;
  }

  it("login sends credentials and returns the parsed user", async () => {
    mockFetch().mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => USER,
    });

    const user = await login("http://api.test", {
      email: "jose@example.com",
      password: "long-enough-pass",
    });

    expect(user.id).toBe("u-1");
    expect(mockFetch()).toHaveBeenCalledWith(
      "http://api.test/api/auth/login",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        body: JSON.stringify({
          email: "jose@example.com",
          password: "long-enough-pass",
          turnstile_token: null,
        }),
      }),
    );
  });

  it("register surfaces the backend error code via AuthApiError", async () => {
    mockFetch().mockResolvedValueOnce({
      ok: false,
      status: 409,
      json: async () => ({ detail: "email_taken" }),
    });

    const attempt = register("http://api.test", {
      email: "jose@example.com",
      password: "long-enough-pass",
    });

    await expect(attempt).rejects.toMatchObject({ status: 409, detail: "email_taken" });
    await expect(
      register("http://api.test", { email: "x@x.es", password: "p".repeat(8) }),
    ).rejects.toBeInstanceOf(Error); // fetch mock exhausted → network-ish failure
  });

  it("fetchCurrentUser maps 401 to null instead of throwing", async () => {
    mockFetch().mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ detail: "not authenticated" }),
    });
    await expect(fetchCurrentUser("http://api.test")).resolves.toBeNull();
  });

  it("fetchCurrentUser returns the user when the session is live", async () => {
    mockFetch().mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => USER,
    });
    const me = await fetchCurrentUser("http://api.test");
    expect(me?.email).toBe("jose@example.com");
  });

  it("resetPassword posts token + new password and resolves on 204", async () => {
    mockFetch().mockResolvedValueOnce({ ok: true, status: 204, json: async () => ({}) });
    await expect(
      resetPassword("http://api.test", "tok-123", "a-new-long-password"),
    ).resolves.toBeUndefined();
    expect(mockFetch()).toHaveBeenCalledWith(
      "http://api.test/api/auth/password/reset",
      expect.objectContaining({
        body: JSON.stringify({ token: "tok-123", new_password: "a-new-long-password" }),
      }),
    );
  });

  it("AuthApiError formats status and detail", () => {
    const error = new AuthApiError(403, "email_not_verified");
    expect(error.message).toContain("403");
    expect(error.message).toContain("email_not_verified");
  });
});
