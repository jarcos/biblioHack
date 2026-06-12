import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BrowsePage } from "../src/components/BrowsePage";

function summary(titn: number, title: string, genre = "narrative"): unknown {
  return {
    titn,
    title,
    authors: ["García Márquez, Gabriel"],
    publisher: "Editorial",
    pub_year: 1967,
    copies_count: 1,
    audience: "adult",
    literary_form: "literary",
    genre,
    available_count: 0,
    cover: null,
  };
}

function browseBody(): unknown {
  return {
    total: 2,
    limit: 24,
    offset: 0,
    has_more: false,
    items: [summary(1, "Cien años de soledad"), summary(3, "Romancero gitano", "poetry")],
    facets: {
      genre: [
        { value: "narrative", count: 1 },
        { value: "poetry", count: 1 },
      ],
      language: [{ value: "spa", count: 2 }],
      audience: [{ value: "adult", count: 2 }],
      literary_form: [{ value: "literary", count: 2 }],
    },
  };
}

describe("BrowsePage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;
    mockFetch.mockImplementation((input: unknown) => {
      const url = String(input);
      const body = url.includes("/catalog/authors") ? { items: [] } : browseBody();
      return Promise.resolve({ ok: true, status: 200, json: async () => body });
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the grid and the facet counts", async () => {
    render(<BrowsePage apiBaseUrl="http://api.test" />);

    expect(await screen.findByText("Cien años de soledad")).toBeInTheDocument();
    expect(screen.getByText(/2 obras en el espejo/i)).toBeInTheDocument();
    // Facet groups render with Spanish labels.
    expect(screen.getByRole("button", { name: /narrativa/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /poesía 1/i })).toBeInTheDocument();
  });

  it("clicking a facet value refetches with the filter applied", async () => {
    const user = userEvent.setup();
    render(<BrowsePage apiBaseUrl="http://api.test" />);

    await user.click(await screen.findByRole("button", { name: /poesía/i }));

    await waitFor(() => {
      const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;
      const browseCalls = mockFetch.mock.calls
        .map((call) => String(call[0]))
        .filter((url) => url.includes("/catalog/browse"));
      expect(browseCalls.at(-1)).toContain("genre=poetry");
    });
  });

  it("shows the friendly empty state when no records match", async () => {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;
    mockFetch.mockImplementation((input: unknown) => {
      const url = String(input);
      const body = url.includes("/catalog/authors")
        ? { items: [] }
        : { total: 0, limit: 24, offset: 0, has_more: false, items: [], facets: {} };
      return Promise.resolve({ ok: true, status: 200, json: async () => body });
    });

    render(<BrowsePage apiBaseUrl="http://api.test" />);

    expect(await screen.findByText(/el catálogo crece cada hora/i)).toBeInTheDocument();
  });
});
