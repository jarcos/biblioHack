import { describe, expect, it } from "vitest";

import { BranchSchema, haversineKm } from "../src/infrastructure/api/branches";

describe("haversineKm", () => {
  it("is ~0 for the same point", () => {
    const p = { lat: 37.3886, lng: -5.9823 };
    expect(haversineKm(p, p)).toBeCloseTo(0, 5);
  });

  it("matches a known Sevilla→Granada distance (~210 km)", () => {
    const sevilla = { lat: 37.3886, lng: -5.9823 };
    const granada = { lat: 37.1773, lng: -3.5986 };
    const km = haversineKm(sevilla, granada);
    expect(km).toBeGreaterThan(195);
    expect(km).toBeLessThan(225);
  });

  it("is symmetric", () => {
    const a = { lat: 36.7497, lng: -3.0206 };
    const b = { lat: 36.85, lng: -2.95 };
    expect(haversineKm(a, b)).toBeCloseTo(haversineKm(b, a), 9);
  });
});

describe("BranchSchema", () => {
  it("accepts a branch with null geo", () => {
    const parsed = BranchSchema.parse({
      code: "AL03",
      name: "Adra",
      municipality: "Adra",
      province: "Almería",
      lat: null,
      lng: null,
    });
    expect(parsed.code).toBe("AL03");
    expect(parsed.lat).toBeNull();
  });
});
