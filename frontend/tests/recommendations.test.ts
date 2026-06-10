import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import {
  RecommendationsResponseSchema,
  fetchRecommendations,
} from "../src/infrastructure/api/recommendations";

const ITEM = {
  record: {
    titn: 7,
    title: "Nada",
    authors: ["Carmen Laforet"],
    copies_count: 3,
    audience: "adult",
    literary_form: "literary",
    available_count: 1,
  },
  score: 0.91,
  rationale: "Posguerra íntima, como lo que sueles puntuar alto.",
};

describe("RecommendationsResponseSchema", () => {
  it("accepts a well-formed response", () => {
    const parsed = RecommendationsResponseSchema.parse({ reason: "ok", items: [ITEM] });
    expect(parsed.items[0]?.record.titn).toBe(7);
  });

  it("tolerates a null rationale and unknown reason", () => {
    const parsed = RecommendationsResponseSchema.parse({
      reason: "something-new",
      items: [{ ...ITEM, rationale: null }],
    });
    expect(parsed.reason).toBe("ok"); // .catch fallback
    expect(parsed.items[0]?.rationale).toBeNull();
  });

  it("rejects items without a record", () => {
    expect(() =>
      RecommendationsResponseSchema.parse({ reason: "ok", items: [{ score: 1 }] }),
    ).toThrow();
  });
});

describe("fetchRecommendations", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends credentials and parses the payload", async () => {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ reason: "empty_profile", items: [] }),
    });

    const response = await fetchRecommendations("http://api.test");
    expect(response.reason).toBe("empty_profile");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://api.test/api/recommendations",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("throws on a non-2xx response", async () => {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;
    mockFetch.mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({}) });
    await expect(fetchRecommendations("http://api.test")).rejects.toThrow(/401/);
  });
});
