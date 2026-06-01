import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RecordDetail } from "../src/components/RecordDetail";

/**
 * RecordDetail reads `?titn=` from `window.location` (it ships as a
 * `client:only` island), so each test sets the URL with history.replaceState
 * before rendering.
 */
describe("RecordDetail", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    window.history.replaceState({}, "", "/record");
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function mockRecord(body: unknown): void {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => body,
    });
  }

  it("renders the record with profile badges, subjects and branches", async () => {
    window.history.replaceState({}, "", "/record?titn=42");
    mockRecord({
      titn: 42,
      title: "Trilogía de Nueva York",
      subtitle: null,
      document_type: "Monografías",
      language: "spa",
      pub_year: 1996,
      publisher: "Anagrama",
      classification: '821.111(73)-3"19"',
      audience: "adult",
      literary_form: "literary",
      authors: ["Auster, Paul"],
      subjects: ["Novela estadounidense"],
      isbns: ["9788433920416"],
      copies: [
        { branch_code: "HU01", branch_name: "Huelva Provincial" },
        { branch_code: "HU01", branch_name: "Huelva Provincial" },
        { branch_code: "SE01", branch_name: "Biblioteca de Andalucía" },
      ],
      source_url: "https://example.test/?TITN=42",
    });

    render(<RecordDetail apiBaseUrl="http://api.test" />);

    await waitFor(() => {
      expect(screen.getByText("Trilogía de Nueva York")).toBeInTheDocument();
    });
    expect(screen.getByText("Adultos")).toBeInTheDocument();
    expect(screen.getByText("Literatura")).toBeInTheDocument();
    expect(screen.getByText("Novela estadounidense")).toBeInTheDocument();
    // Two branches; Huelva has 2 copies.
    expect(screen.getByText("Huelva Provincial")).toBeInTheDocument();
    expect(screen.getByText(/2 ejemplares/)).toBeInTheDocument();
    expect(screen.getByText("Biblioteca de Andalucía")).toBeInTheDocument();
    // CDU surfaced.
    expect(screen.getByText(/CDU 821\.111/)).toBeInTheDocument();
  });

  it("shows a friendly message when the record isn't mirrored yet (404)", async () => {
    window.history.replaceState({}, "", "/record?titn=999999");
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: false,
      status: 404,
      statusText: "Not Found",
      json: async () => ({ detail: "No record with TITN=999999 in the mirror yet" }),
    });

    render(<RecordDetail apiBaseUrl="http://api.test" />);

    await waitFor(() => {
      expect(screen.getByText(/aún no está en el espejo/i)).toBeInTheDocument();
    });
  });

  it("prompts for a TITN when the query param is missing and never calls the API", () => {
    render(<RecordDetail apiBaseUrl="http://api.test" />);
    expect(screen.getByText(/falta el identificador/i)).toBeInTheDocument();
    expect(globalThis.fetch as ReturnType<typeof vi.fn>).not.toHaveBeenCalled();
  });

  it("renders availability badges from each copy's latest status", async () => {
    window.history.replaceState({}, "", "/record?titn=50");
    mockRecord({
      titn: 50,
      title: "Con disponibilidad",
      subtitle: null,
      document_type: null,
      language: "spa",
      pub_year: 2000,
      publisher: "Ed",
      classification: null,
      audience: "adult",
      literary_form: "literary",
      authors: [],
      subjects: [],
      isbns: [],
      copies: [
        { branch_code: "HU01", branch_name: "Huelva", status: "available" },
        { branch_code: "HU01", branch_name: "Huelva", status: "loaned" },
        { branch_code: "SE01", branch_name: "Sevilla", status: "loaned" },
      ],
      source_url: "https://example.test/?TITN=50",
    });

    render(<RecordDetail apiBaseUrl="http://api.test" />);

    await waitFor(() => {
      expect(screen.getByText("Con disponibilidad")).toBeInTheDocument();
    });
    // Overall "on shelf now" summary + Huelva shows 1 available, Sevilla loaned.
    expect(screen.getByText("Disponible ahora")).toBeInTheDocument();
    expect(screen.getByText("1 disponible")).toBeInTheDocument();
    expect(screen.getByText("Prestado")).toBeInTheDocument();
  });
});
