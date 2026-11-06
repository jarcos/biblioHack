import { describe, it, expect } from "vitest";
import { umamiScript } from "../src/infrastructure/analytics/umami";

// Usage analytics (06-11-2026, asked by José): Umami on the NAS, the same
// instance FrienDraft, Huelva Developers and VibeCoders & Beers report to.

const SITE_ID = "be1f187c-3f02-4231-8afa-3fccf81c6724";

describe("umamiScript", () => {
  it("renders nothing when no website id was baked into the build", () => {
    // Local `astro dev`, CI and the docker smoke build must not report.
    expect(umamiScript(undefined)).toBeNull();
    expect(umamiScript("")).toBeNull();
    expect(umamiScript("   ")).toBeNull();
  });

  it("loads the tracker from the NAS instance with the site id", () => {
    const attrs = umamiScript(SITE_ID);
    expect(attrs?.src).toBe("https://umami.josearcos.me/script.js");
    expect(attrs?.["data-website-id"]).toBe(SITE_ID);
  });

  it("trims a website id that arrives with stray whitespace from .env", () => {
    expect(umamiScript(`  ${SITE_ID}\n`)?.["data-website-id"]).toBe(SITE_ID);
  });

  it("only reports from the public hostname", () => {
    expect(umamiScript(SITE_ID)?.["data-domains"]).toBe("biblio.josearcos.me");
  });

  it("never sends query strings or hashes: /verify and /reset-password carry tokens there", () => {
    const attrs = umamiScript(SITE_ID);
    expect(attrs?.["data-exclude-search"]).toBe("true");
    expect(attrs?.["data-exclude-hash"]).toBe("true");
  });
});
