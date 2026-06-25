import {
  AUDIENCES,
  GENRES,
  LITERARY_FORMS,
  type Audience,
  type Genre,
  type LiteraryForm,
} from "@infrastructure/api/catalog";

/**
 * Shared `/browse` filter state and URL (de)serialisation.
 *
 * One source of truth so two things stay in sync:
 *  - `BrowsePage` reads its initial filters from the URL and writes them back
 *    as they change (shareable, back/forward-friendly deep links);
 *  - search results and the record page build `/browse?…` links via
 *    `browseHref`, so "explore this author/genre" lands on a pre-filtered page.
 *
 * Optional members spell `| undefined` for `exactOptionalPropertyTypes`.
 */

export type BrowseSort = "relevance" | "newest" | "title";
export type LibraryScope = "mine" | "province" | "full";

const SORTS = ["relevance", "newest", "title"] as const;
const SCOPES = ["mine", "province", "full"] as const;

export interface BrowseFilters {
  author?: string | undefined;
  language?: string | undefined;
  genre?: Genre | undefined;
  audience?: Audience | undefined;
  literaryForm?: LiteraryForm | undefined;
  yearFrom?: number | undefined;
  yearTo?: number | undefined;
  available: boolean;
  sort: BrowseSort;
  libraryScope: LibraryScope;
}

export const DEFAULT_BROWSE_FILTERS: BrowseFilters = {
  available: false,
  sort: "relevance",
  libraryScope: "mine",
};

/** Subset used to build a deep link from elsewhere (e.g. an author badge). */
export type BrowseLink = {
  author?: string;
  language?: string;
  genre?: Genre;
  audience?: Audience;
  literaryForm?: LiteraryForm;
  yearFrom?: number;
  yearTo?: number;
  available?: boolean;
  sort?: BrowseSort;
};

function oneOf<T extends string>(values: readonly T[], raw: string | null): T | undefined {
  return raw !== null && (values as readonly string[]).includes(raw) ? (raw as T) : undefined;
}

function posInt(raw: string | null): number | undefined {
  if (raw === null) return undefined;
  const n = Number(raw);
  return Number.isInteger(n) && n > 0 ? n : undefined;
}

/** Parse `/browse` filters out of a query string (e.g. `location.search`).
 *  Unknown or malformed values fall back to the default rather than throwing. */
export function parseBrowseFilters(search: string): BrowseFilters {
  const p = new URLSearchParams(search);
  return {
    author: p.get("author")?.trim() || undefined,
    language: p.get("language")?.trim() || undefined,
    genre: oneOf(GENRES, p.get("genre")),
    audience: oneOf(AUDIENCES, p.get("audience")),
    literaryForm: oneOf(LITERARY_FORMS, p.get("form")),
    yearFrom: posInt(p.get("yearFrom")),
    yearTo: posInt(p.get("yearTo")),
    available: p.get("available") === "true",
    sort: oneOf(SORTS, p.get("sort")) ?? DEFAULT_BROWSE_FILTERS.sort,
    libraryScope: oneOf(SCOPES, p.get("scope")) ?? DEFAULT_BROWSE_FILTERS.libraryScope,
  };
}

/** Serialise filters to a query string, omitting anything left at its default
 *  so a clean `/browse` stays clean. */
export function browseSearchParams(f: BrowseFilters): URLSearchParams {
  const p = new URLSearchParams();
  if (f.author) p.set("author", f.author);
  if (f.language) p.set("language", f.language);
  if (f.genre) p.set("genre", f.genre);
  if (f.audience) p.set("audience", f.audience);
  if (f.literaryForm) p.set("form", f.literaryForm);
  if (f.yearFrom !== undefined) p.set("yearFrom", String(f.yearFrom));
  if (f.yearTo !== undefined) p.set("yearTo", String(f.yearTo));
  if (f.available) p.set("available", "true");
  if (f.sort !== DEFAULT_BROWSE_FILTERS.sort) p.set("sort", f.sort);
  if (f.libraryScope !== DEFAULT_BROWSE_FILTERS.libraryScope) p.set("scope", f.libraryScope);
  return p;
}

/** Build a `/browse?…` href pre-filtered by the given fields. */
export function browseHref(link: BrowseLink): string {
  const filters: BrowseFilters = { ...DEFAULT_BROWSE_FILTERS, ...link };
  const qs = browseSearchParams(filters).toString();
  return qs ? `/browse?${qs}` : "/browse";
}
