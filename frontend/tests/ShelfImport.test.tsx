import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ShelfImport } from "../src/components/ShelfImport";

function shelfBody(total: number): unknown {
  return {
    counts: { total, matched: 0, read: total, currently_reading: 0, to_read: 0 },
    read: [],
    currently_reading: [],
    to_read: [],
  };
}

function renderWithClient(): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ShelfImport apiBaseUrl="http://api.test" />
    </QueryClientProvider>,
  );
}

describe("ShelfImport", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function mockShelfResponse(total: number): void {
    const mockFetch = globalThis.fetch as ReturnType<typeof vi.fn>;
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => shelfBody(total),
    });
  }

  it("shows the prominent import button when the shelf is empty", async () => {
    mockShelfResponse(0);
    renderWithClient();

    expect(
      await screen.findByRole("button", { name: /importar csv de goodreads/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/sin duplicarlos/i)).not.toBeInTheDocument();
  });

  it("collapses to a discreet re-import link once a shelf exists", async () => {
    mockShelfResponse(42);
    renderWithClient();

    const link = await screen.findByRole("button", { name: /re-importar csv de goodreads/i });
    expect(link).toBeInTheDocument();
    // The prominent uploader affordances are gone in the collapsed state.
    expect(screen.queryByText(/goodreads → import\/export/i)).not.toBeInTheDocument();
    // The link explains that re-importing updates rather than duplicates.
    expect(screen.getByText(/sin duplicarlos/i)).toBeInTheDocument();
  });

  it("expands back to the uploader when the re-import link is clicked", async () => {
    mockShelfResponse(42);
    renderWithClient();

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /re-importar csv de goodreads/i }));

    // Expanded: the full uploader is back (re-import wording + the help text).
    expect(screen.getByRole("button", { name: /re-importar csv de goodreads/i })).toBeEnabled();
    expect(screen.getByText(/goodreads → import\/export/i)).toBeInTheDocument();
  });
});
