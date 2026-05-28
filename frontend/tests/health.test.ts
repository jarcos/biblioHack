import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fetchHealth, HealthSchema } from "../src/infrastructure/api/health";

describe("HealthSchema", () => {
  it("accepts a well-formed response", () => {
    const parsed = HealthSchema.parse({ status: "ok", version: "0.1.0" });
    expect(parsed.version).toBe("0.1.0");
  });

  it("rejects an unexpected status", () => {
    expect(() => HealthSchema.parse({ status: "down", version: "0.1.0" })).toThrow();
  });

  it("rejects a missing version", () => {
    expect(() => HealthSchema.parse({ status: "ok" })).toThrow();
  });
});

describe("fetchHealth", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the parsed health payload on 200", async () => {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ status: "ok", version: "0.1.0" }),
    });

    const health = await fetchHealth("http://api.test");
    expect(health).toEqual({ status: "ok", version: "0.1.0" });
    expect(mockFetch).toHaveBeenCalledWith(
      "http://api.test/healthz",
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("throws on a non-2xx response", async () => {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 503,
      json: async () => ({}),
    });

    await expect(fetchHealth("http://api.test")).rejects.toThrow(/503/);
  });
});
