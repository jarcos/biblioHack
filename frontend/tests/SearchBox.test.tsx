import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SearchBox } from "../src/components/SearchBox";

describe("SearchBox", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function mockSearchResponse(body: unknown): void {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => body,
    });
  }

  it("shows an idle prompt before any query is submitted", () => {
    render(<SearchBox apiBaseUrl="http://api.test" />);
    expect(screen.getByText(/escribe una consulta/i)).toBeInTheDocument();
  });

  it("disables the submit button while the input is empty", () => {
    render(<SearchBox apiBaseUrl="http://api.test" />);
    expect(screen.getByRole("button", { name: /buscar/i })).toBeDisabled();
  });

  it("renders results after a successful submit", async () => {
    mockSearchResponse({
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
    });

    const user = userEvent.setup();
    render(<SearchBox apiBaseUrl="http://api.test" />);

    await user.type(screen.getByLabelText(/buscar en el catálogo/i), "soledad");
    await user.click(screen.getByRole("button", { name: /buscar/i }));

    await waitFor(() => {
      expect(screen.getByText("Cien años de soledad")).toBeInTheDocument();
    });
    expect(screen.getByText(/3 ejemplares/i)).toBeInTheDocument();
    expect(screen.getByText(/1 resultado para/i)).toBeInTheDocument();
  });

  it("renders the polite empty state when the backend returns no rows", async () => {
    mockSearchResponse({
      query: "rarísimo",
      total: 0,
      limit: 20,
      offset: 0,
      has_more: false,
      items: [],
    });

    const user = userEvent.setup();
    render(<SearchBox apiBaseUrl="http://api.test" />);
    await user.type(screen.getByLabelText(/buscar en el catálogo/i), "rarísimo");
    await user.click(screen.getByRole("button", { name: /buscar/i }));

    await waitFor(() => {
      expect(screen.getByText(/sin resultados para/i)).toBeInTheDocument();
    });
  });

  it("renders the error state when the backend returns non-2xx", async () => {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;
    // URL-aware: 503 for the search, benign for the availability hook's branch
    // fetches (which fire on mount), so call ordering doesn't matter.
    mockFetch.mockImplementation((url: string) =>
      Promise.resolve(
        String(url).includes("/catalog/search")
          ? {
              ok: false,
              status: 503,
              statusText: "Service Unavailable",
              json: async () => ({ detail: "Database down" }),
            }
          : { ok: true, status: 200, json: async () => ({ branches: [], codes: [] }) },
      ),
    );

    const user = userEvent.setup();
    render(<SearchBox apiBaseUrl="http://api.test" />);
    await user.type(screen.getByLabelText(/buscar en el catálogo/i), "hello");
    await user.click(screen.getByRole("button", { name: /buscar/i }));

    await waitFor(() => {
      expect(screen.getByText(/no se pudo completar/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/503/)).toBeInTheDocument();
  });

  it("searches with scope=all once the include-everything toggle is on", async () => {
    mockSearchResponse({
      query: "x",
      total: 0,
      limit: 20,
      offset: 0,
      has_more: false,
      items: [],
    });

    const user = userEvent.setup();
    render(<SearchBox apiBaseUrl="http://api.test" />);

    await user.click(screen.getByRole("checkbox", { name: /incluir infantil/i }));
    await user.type(screen.getByLabelText(/buscar en el catálogo/i), "x");
    await user.click(screen.getByRole("button", { name: /buscar/i }));

    await waitFor(() => {
      const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;
      expect(mockFetch).toHaveBeenCalled();
      // The availability hook also fetches branches, so assert *some* call is
      // the scoped search rather than assuming it's the most recent one.
      const calledScopeAll = mockFetch.mock.calls.some((c) => String(c[0]).includes("scope=all"));
      expect(calledScopeAll).toBe(true);
    });
  });

  it("shows an 'available now' badge when a result has copies on the shelf", async () => {
    mockSearchResponse({
      query: "x",
      total: 1,
      limit: 20,
      offset: 0,
      has_more: false,
      items: [
        {
          titn: 1,
          title: "Disponible",
          authors: [],
          publisher: null,
          pub_year: null,
          copies_count: 3,
          available_count: 2,
        },
      ],
    });

    const user = userEvent.setup();
    render(<SearchBox apiBaseUrl="http://api.test" />);
    await user.type(screen.getByLabelText(/buscar en el catálogo/i), "x");
    await user.click(screen.getByRole("button", { name: /buscar/i }));

    await waitFor(() => {
      expect(screen.getByText("2 disp.")).toBeInTheDocument();
    });
  });
});
