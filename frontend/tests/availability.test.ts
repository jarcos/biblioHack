import { describe, expect, it } from "vitest";

import {
  countNearbyAvailable,
  describeAvailability,
  type AvailabilityAnchor,
  type BranchCoord,
} from "../src/lib/availability";

/**
 * Pure-logic tests for the library-aware availability badge. All distance math
 * is client-side, so this is where the badge's correctness lives.
 */

// Huelva (primary), a branch ~4 km away, Sevilla ~85 km away, and one branch
// we couldn't geocode.
const HU01 = { lat: 37.2614, lng: -6.9447 };
const HU_NEAR = { lat: 37.3, lng: -6.94 };
const SE01 = { lat: 37.3886, lng: -5.9823 };

const branches: ReadonlyMap<string, BranchCoord> = new Map<string, BranchCoord>([
  ["HU01", HU01],
  ["HU-NEAR", HU_NEAR],
  ["SE01", SE01],
  ["NOGEO", { lat: null, lng: null }],
]);

const primaryAnchor: AvailabilityAnchor = { kind: "primary", code: "HU01", ...HU01 };
const gpsAnchor: AvailabilityAnchor = { kind: "gps", ...HU01 };

describe("countNearbyAvailable", () => {
  it("counts available branches within the radius, excluding the anchor branch", () => {
    const n = countNearbyAvailable(
      ["HU01", "HU-NEAR", "SE01", "NOGEO"],
      branches,
      HU01,
      25,
      "HU01",
    );
    expect(n).toBe(1); // HU-NEAR only: HU01 excluded, SE01 too far, NOGEO unplaceable
  });

  it("includes far branches once the radius is wide enough", () => {
    const n = countNearbyAvailable(["HU-NEAR", "SE01"], branches, HU01, 100);
    expect(n).toBe(2);
  });

  it("never counts ungeocoded branches", () => {
    expect(countNearbyAvailable(["NOGEO"], branches, HU01, 10_000)).toBe(0);
  });
});

describe("describeAvailability", () => {
  it("no anchor → 'N disp.' fallback and offers to locate", () => {
    const view = describeAvailability(
      { available_count: 7, available_branch_codes: ["HU01", "SE01"] },
      null,
      branches,
      25,
    );
    expect(view.label).toBe("7 disp.");
    expect(view.offerLocate).toBe(true);
  });

  it("no anchor, nothing available → no pill but still offers to locate", () => {
    const view = describeAvailability(
      { available_count: 0, available_branch_codes: [] },
      null,
      branches,
      25,
    );
    expect(view.label).toBeNull();
    expect(view.offerLocate).toBe(true);
  });

  it("available at the primary library, with more nearby", () => {
    const view = describeAvailability(
      { available_count: 3, available_branch_codes: ["HU01", "HU-NEAR"] },
      primaryAnchor,
      branches,
      25,
    );
    expect(view.label).toBe("Disponible en tu biblioteca");
    expect(view.nearby).toBe("+1 cercana");
    expect(view.variant).toBe("available");
  });

  it("pluralises the nearby chip", () => {
    const map = new Map<string, BranchCoord>(branches);
    map.set("HU-NEAR2", { lat: 37.31, lng: -6.95 });
    const view = describeAvailability(
      { available_count: 4, available_branch_codes: ["HU01", "HU-NEAR", "HU-NEAR2"] },
      primaryAnchor,
      map,
      25,
    );
    expect(view.nearby).toBe("+2 cercanas");
  });

  it("not at the primary library, but available nearby", () => {
    const view = describeAvailability(
      { available_count: 2, available_branch_codes: ["HU-NEAR"] },
      primaryAnchor,
      branches,
      25,
    );
    expect(view.label).toBe("No en tu biblioteca · 1 cercana");
    expect(view.nearby).toBeNull();
  });

  it("not at primary, none nearby, but available elsewhere → network fallback", () => {
    const view = describeAvailability(
      { available_count: 5, available_branch_codes: ["SE01"] },
      primaryAnchor,
      branches,
      25,
    );
    expect(view.label).toBe("Disponible en la red");
  });

  it("nowhere available → no pill", () => {
    const view = describeAvailability(
      { available_count: 0, available_branch_codes: [] },
      primaryAnchor,
      branches,
      25,
    );
    expect(view.label).toBeNull();
  });

  it("GPS anchor phrases nearby without 'tu biblioteca'", () => {
    const view = describeAvailability(
      { available_count: 2, available_branch_codes: ["HU-NEAR", "SE01"] },
      gpsAnchor,
      branches,
      25,
    );
    expect(view.label).toBe("1 biblioteca cerca"); // HU-NEAR in range, SE01 not
    expect(view.offerLocate).toBe(false);
  });
});
