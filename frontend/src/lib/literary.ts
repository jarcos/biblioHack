import type { Audience, Genre, LiteraryForm } from "@infrastructure/api/catalog";

/**
 * Presentation helpers for the literary profile (audience + form). The
 * canonical values live on the backend (`literary_profile.py`); here we map
 * them to Spanish UI labels and a `Badge` variant. Both are tolerant: an
 * unrecognised value reads as "Sin clasificar" rather than throwing.
 */

const AUDIENCE_LABELS: Record<Audience, string> = {
  adult: "Adultos",
  youth: "Juvenil",
  children: "Infantil",
  unknown: "Sin clasificar",
};

const FORM_LABELS: Record<LiteraryForm, string> = {
  literary: "Literatura",
  nonfiction: "No ficción",
  unknown: "Sin clasificar",
};

const GENRE_LABELS: Record<Genre, string> = {
  narrative: "Narrativa",
  poetry: "Poesía",
  drama: "Teatro",
  essay: "Ensayo",
  comic: "Cómic",
  unknown: "Sin clasificar",
};

export function genreLabel(genre: string): string {
  return GENRE_LABELS[genre as Genre] ?? GENRE_LABELS.unknown;
}

export function audienceLabel(audience: string): string {
  return AUDIENCE_LABELS[audience as Audience] ?? AUDIENCE_LABELS.unknown;
}

export function formLabel(form: string): string {
  return FORM_LABELS[form as LiteraryForm] ?? FORM_LABELS.unknown;
}

/**
 * Whether a record sits inside the default "literary" scope (adult-or-unknown
 * audience AND literary-or-unknown form). Mirrors `LiteraryProfile.in_default_scope`
 * on the backend — used to flag, in `scope=all` mode, the rows that the
 * default view would otherwise hide.
 */
export function inDefaultScope(audience: string, form: string): boolean {
  const audienceOk = audience === "adult" || audience === "unknown";
  const formOk = form === "literary" || form === "unknown";
  return audienceOk && formOk;
}
