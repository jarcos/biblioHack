import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CatalogApiError, fetchRecord, searchCatalog } from "../src/infrastructure/api/catalog";

describe("searchCatalog", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the parsed page on 200", async () => {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        query: "soledad",
        total: 1,
        limit: 20,
        offset: 0,
        has_more: false,
        items: [
          {
            titn: 1,
            title: "Cien años de soledad",
            authors: ["García Márquez, Gabriel"],
            publisher: "Editorial Sudamericana",
            pub_year: 1967,
            copies_count: 3,
          },
        ],
      }),
    });

    const result = await searchCatalog("http://api.test", { query: "soledad" });
    expect(result.total).toBe(1);
    expect(result.items[0]?.title).toBe("Cien años de soledad");

    const calledUrl = mockFetch.mock.calls[0]?.[0] as string;
    expect(calledUrl).toBe("http://api.test/catalog/search?q=soledad");
  });

  it("forwards limit + offset as query params when provided", async () => {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        query: "x",
        total: 0,
        limit: 5,
        offset: 10,
        has_more: false,
        items: [],
      }),
    });

    await searchCatalog("http://api.test", { query: "x", limit: 5, offset: 10 });

    const calledUrl = mockFetch.mock.calls[0]?.[0] as string;
    expect(calledUrl).toContain("q=x");
    expect(calledUrl).toContain("limit=5");
    expect(calledUrl).toContain("offset=10");
  });

  it("returns an empty items array shape unchanged", async () => {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        query: "nothing",
        total: 0,
        limit: 20,
        offset: 0,
        has_more: false,
        items: [],
      }),
    });

    const result = await searchCatalog("http://api.test", { query: "nothing" });
    expect(result.items).toEqual([]);
    expect(result.total).toBe(0);
    expect(result.has_more).toBe(false);
  });

  it("throws CatalogApiError(422) when the backend rejects the query", async () => {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 422,
      statusText: "Unprocessable Content",
      json: async () => ({ detail: "Query must be non-empty" }),
    });

    await expect(searchCatalog("http://api.test", { query: "" })).rejects.toBeInstanceOf(
      CatalogApiError,
    );
  });
});

describe("fetchRecord", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the parsed record on 200", async () => {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        titn: 42,
        title: "Test record",
        subtitle: null,
        document_type: "Monografías",
        language: "spa",
        pub_year: 2020,
        publisher: "Test Press",
        classification: null,
        authors: ["Test, Author"],
        subjects: [],
        isbns: [],
        copies: [{ branch_code: "HU01", branch_name: "Huelva Provincial" }],
        source_url: "https://example.test/?TITN=42",
      }),
    });

    const record = await fetchRecord("http://api.test", 42);
    expect(record.titn).toBe(42);
    expect(record.authors).toEqual(["Test, Author"]);
    expect(record.copies).toHaveLength(1);
  });

  it("raises CatalogApiError(404) with the detail body when TITN is missing", async () => {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      statusText: "Not Found",
      json: async () => ({ detail: "No record with TITN=999999 in the mirror yet" }),
    });

    const promise = fetchRecord("http://api.test", 999999);
    await expect(promise).rejects.toBeInstanceOf(CatalogApiError);
    await expect(promise).rejects.toMatchObject({
      status: 404,
      detail: expect.stringContaining("999999"),
    });
  });

  it("falls back to statusText when the response body isn't JSON", async () => {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      json: async () => {
        throw new Error("not JSON");
      },
    });

    await expect(fetchRecord("http://api.test", 1)).rejects.toMatchObject({
      status: 500,
      detail: "Internal Server Error",
    });
  });

  it("parses audience + literary_form when present", async () => {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        titn: 7,
        title: "Un cuento infantil",
        subtitle: null,
        document_type: "Monografías",
        language: "spa",
        pub_year: 2018,
        publisher: "SM",
        classification: "087.5",
        audience: "children",
        literary_form: "literary",
        authors: [],
        subjects: ["Cuentos infantiles"],
        isbns: [],
        copies: [],
        source_url: "https://example.test/?TITN=7",
      }),
    });

    const record = await fetchRecord("http://api.test", 7);
    expect(record.audience).toBe("children");
    expect(record.literary_form).toBe("literary");
  });
});

describe("catalog scope + literary profile", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function mockEmptyPage(): void {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        query: "x",
        total: 0,
        limit: 20,
        offset: 0,
        has_more: false,
        items: [],
      }),
    });
  }

  it("adds scope=all to the URL when scope is 'all'", async () => {
    mockEmptyPage();
    await searchCatalog("http://api.test", { query: "x", scope: "all" });
    const calledUrl = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]?.[0] as string;
    expect(calledUrl).toContain("scope=all");
  });

  it("omits scope from the URL by default", async () => {
    mockEmptyPage();
    await searchCatalog("http://api.test", { query: "x" });
    const calledUrl = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]?.[0] as string;
    expect(calledUrl).not.toContain("scope=");
  });

  it("defaults audience + literary_form to 'unknown' when the backend omits them", async () => {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        query: "x",
        total: 1,
        limit: 20,
        offset: 0,
        has_more: false,
        items: [
          {
            titn: 1,
            title: "Legacy-shaped row",
            authors: [],
            publisher: null,
            pub_year: null,
            copies_count: 0,
          },
        ],
      }),
    });

    const result = await searchCatalog("http://api.test", { query: "x" });
    expect(result.items[0]?.audience).toBe("unknown");
    expect(result.items[0]?.literary_form).toBe("unknown");
  });

  it("degrades an unrecognised profile value to 'unknown' instead of throwing", async () => {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        query: "x",
        total: 1,
        limit: 20,
        offset: 0,
        has_more: false,
        items: [
          {
            titn: 2,
            title: "Weird profile",
            authors: [],
            publisher: null,
            pub_year: null,
            copies_count: 1,
            audience: "martian",
            literary_form: "interpretive-dance",
          },
        ],
      }),
    });

    const result = await searchCatalog("http://api.test", { query: "x" });
    expect(result.items[0]?.audience).toBe("unknown");
    expect(result.items[0]?.literary_form).toBe("unknown");
  });
});
