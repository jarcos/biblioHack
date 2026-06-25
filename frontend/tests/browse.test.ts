import { describe, expect, it } from "vitest";

import {
  browseHref,
  browseSearchParams,
  DEFAULT_BROWSE_FILTERS,
  parseBrowseFilters,
} from "../src/lib/browse";

describe("browseHref", () => {
  it("builds a clean /browse for an empty link", () => {
    expect(browseHref({})).toBe("/browse");
  });

  it("encodes an author cross-link", () => {
    expect(browseHref({ author: "García Márquez, Gabriel" })).toBe(
      "/browse?author=Garc%C3%ADa+M%C3%A1rquez%2C+Gabriel",
    );
  });

  it("encodes a genre cross-link", () => {
    expect(browseHref({ genre: "poetry" })).toBe("/browse?genre=poetry");
  });

  it("omits fields left at their default (sort, scope)", () => {
    expect(browseHref({ sort: "relevance" })).toBe("/browse");
    expect(browseHref({ sort: "newest" })).toBe("/browse?sort=newest");
  });
});

describe("parseBrowseFilters", () => {
  it("returns defaults for an empty query", () => {
    expect(parseBrowseFilters("")).toEqual(DEFAULT_BROWSE_FILTERS);
  });

  it("reads author, genre and year range", () => {
    const f = parseBrowseFilters("?author=Auster&genre=narrative&yearFrom=1980&yearTo=1990");
    expect(f.author).toBe("Auster");
    expect(f.genre).toBe("narrative");
    expect(f.yearFrom).toBe(1980);
    expect(f.yearTo).toBe(1990);
  });

  it("drops unknown enum values and non-positive years", () => {
    const f = parseBrowseFilters("?genre=bogus&audience=martian&yearFrom=0&yearTo=-5");
    expect(f.genre).toBeUndefined();
    expect(f.audience).toBeUndefined();
    expect(f.yearFrom).toBeUndefined();
    expect(f.yearTo).toBeUndefined();
  });

  it("round-trips through browseSearchParams", () => {
    const original = "?author=Borges&genre=essay&available=true&sort=newest&form=nonfiction";
    const parsed = parseBrowseFilters(original);
    const rebuilt = parseBrowseFilters(`?${browseSearchParams(parsed).toString()}`);
    expect(rebuilt).toEqual(parsed);
  });
});
