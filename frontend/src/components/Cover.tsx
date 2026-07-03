import type { CSSProperties, ReactElement } from "react";

/**
 * Cover — procedural typographic book cover, used whenever a record has no
 * scanned cover image (most of the mirror).
 *
 * Port of the design handoff's `Cover.dc.html`: instead of a repeated
 * placeholder icon, we compose a cloth jacket. A stable hash of
 * `title|author` picks one of ten cloth palettes and one of three layouts
 * — framed / banded / classic — so every book is recognisable at a glance
 * and a shelf of fallbacks still breathes.
 *
 * Colors are intentionally literal hex (cloth dyes, not UI tokens): the
 * jackets read the same in light and dark themes, like real books do.
 * Deterministic and hook-free, so it server-renders in Astro islands
 * without hydration cost.
 */

interface Props {
  title: string;
  author?: string | undefined;
  /** width/height aspect ratio; the design's default is 0.66 (≈ trade paperback). */
  ratio?: number;
  className?: string;
}

interface Palette {
  bg: string;
  spine: string;
  rule: string;
  text: string;
}

const PALETTES: readonly Palette[] = [
  { bg: "#2C4A3A", spine: "#1F382C", rule: "#7FA98E", text: "#F0E9D6" },
  { bg: "#6E2C2C", spine: "#521F1F", rule: "#C79A8E", text: "#F1E4DA" },
  { bg: "#26384F", spine: "#1B2A3D", rule: "#8CA2BC", text: "#E9EDF3" },
  { bg: "#8A5A18", spine: "#684310", rule: "#D8B57E", text: "#F5EAD4" },
  { bg: "#48304E", spine: "#35233A", rule: "#B296BB", text: "#EEE5F0" },
  { bg: "#39404A", spine: "#2A3038", rule: "#9AA4B0", text: "#EBEDF0" },
  { bg: "#1F4A46", spine: "#153733", rule: "#7FB4AD", text: "#E6F0ED" },
  { bg: "#8A492A", spine: "#69381F", rule: "#D6A585", text: "#F4E7DC" },
  { bg: "#5A5326", spine: "#423D1A", rule: "#BFB77E", text: "#F1ECD6" },
  { bg: "#3A2C22", spine: "#2A2019", rule: "#B79A86", text: "#EFE3D7" },
];

/** Deterministic 31-bit string hash (same as the design prototype). */
function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) & 0x7fffffff;
  return h;
}

const clamp = (lines: number): CSSProperties => ({
  display: "-webkit-box",
  WebkitLineClamp: lines,
  WebkitBoxOrient: "vertical",
  overflow: "hidden",
});

export function Cover({ title, author, ratio = 0.66, className }: Props): ReactElement {
  const safeTitle = title || "Sin título";
  const safeAuthor = author ?? "Autor desconocido";
  const h = hash(`${safeTitle}|${safeAuthor}`);
  const p = PALETTES[h % PALETTES.length] as Palette;
  const variant = Math.floor(h / 7) % 3;
  const shelfmark = `${(h % 900) + 100}.${(Math.floor(h / 13) % 90) + 10}`;

  const jacket: CSSProperties = {
    position: "relative",
    width: "100%",
    aspectRatio: String(ratio),
    borderRadius: "3px 5px 5px 3px",
    overflow: "hidden",
    background: p.bg,
    boxShadow: `inset 6px 0 0 ${p.spine}, inset 7px 0 6px -4px rgba(0,0,0,.45), inset 0 0 0 1px rgba(0,0,0,.12)`,
    fontFamily: "'Spectral', Georgia, serif",
    color: p.text,
    display: "flex",
    flexDirection: "column",
  };

  const sheen: CSSProperties = {
    position: "absolute",
    inset: 0,
    background: "radial-gradient(120% 90% at 80% 0%, rgba(255,255,255,.10), rgba(0,0,0,.16))",
    pointerEvents: "none",
  };

  const authorStyle: CSSProperties = {
    fontFamily: "'IBM Plex Sans', sans-serif",
    letterSpacing: ".13em",
    textTransform: "uppercase",
    opacity: 0.82,
    ...clamp(2),
  };

  return (
    <div
      className={className}
      style={jacket}
      role="img"
      aria-label={`${safeTitle} — ${safeAuthor}`}
    >
      <div style={sheen} />

      {variant === 0 && (
        /* Framed — centred title inside a hairline frame */
        <div
          style={{
            position: "relative",
            flex: 1,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            textAlign: "center",
            padding: "14% 12% 12% calc(12% + 6px)",
          }}
        >
          <div
            style={{
              width: "100%",
              border: `1px solid ${p.rule}`,
              borderRadius: "2px",
              flex: 1,
              display: "flex",
              flexDirection: "column",
              justifyContent: "center",
              alignItems: "center",
              gap: "8%",
              padding: "10% 8%",
            }}
          >
            <div
              style={{
                fontFamily: "'IBM Plex Mono', monospace",
                fontSize: "0.5rem",
                letterSpacing: ".22em",
                opacity: 0.6,
              }}
            >
              BIBLIOHACK
            </div>
            <div
              className="font-serif"
              style={{
                fontWeight: 600,
                fontSize: "1.02rem",
                lineHeight: 1.14,
                letterSpacing: "-.01em",
                ...clamp(4),
              }}
            >
              {safeTitle}
            </div>
            <div style={{ width: "22px", height: "1px", background: p.rule }} />
            <div style={{ fontSize: "0.6rem", letterSpacing: ".14em", ...authorStyle }}>
              {safeAuthor}
            </div>
          </div>
        </div>
      )}

      {variant === 1 && (
        /* Banded — spine-color title band across the top */
        <div
          style={{
            position: "relative",
            flex: 1,
            display: "flex",
            flexDirection: "column",
            paddingLeft: "6px",
          }}
        >
          <div
            style={{
              background: p.spine,
              padding: "16% 12% 14% 12%",
              display: "flex",
              flexDirection: "column",
              gap: "6px",
              boxShadow: "0 1px 0 rgba(255,255,255,.08)",
            }}
          >
            <div
              style={{
                fontFamily: "'IBM Plex Mono', monospace",
                fontSize: "0.5rem",
                letterSpacing: ".2em",
                opacity: 0.65,
              }}
            >
              ESPEJO · RBPA
            </div>
            <div
              className="font-serif"
              style={{
                fontWeight: 600,
                fontSize: "1.05rem",
                lineHeight: 1.12,
                letterSpacing: "-.01em",
                ...clamp(4),
              }}
            >
              {safeTitle}
            </div>
          </div>
          <div style={{ flex: 1 }} />
          <div style={{ fontSize: "0.62rem", padding: "0 12% 14% 12%", ...authorStyle }}>
            {safeAuthor}
          </div>
        </div>
      )}

      {variant === 2 && (
        /* Classic — shelfmark, top-aligned title, rule + dot ornament */
        <div
          style={{
            position: "relative",
            flex: 1,
            display: "flex",
            flexDirection: "column",
            padding: "16% 12% 13% calc(12% + 6px)",
          }}
        >
          <div
            style={{
              fontFamily: "'IBM Plex Mono', monospace",
              fontSize: "0.5rem",
              letterSpacing: ".2em",
              opacity: 0.6,
              marginBottom: "9%",
            }}
          >
            N.º {shelfmark}
          </div>
          <div
            className="font-serif"
            style={{
              fontWeight: 600,
              fontSize: "1.12rem",
              lineHeight: 1.12,
              letterSpacing: "-.015em",
              ...clamp(4),
            }}
          >
            {safeTitle}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", margin: "9% 0" }}>
            <div style={{ width: "26px", height: "1px", background: p.rule }} />
            <div style={{ width: "3px", height: "3px", borderRadius: "50%", background: p.rule }} />
          </div>
          <div style={{ flex: 1 }} />
          <div style={{ fontSize: "0.64rem", ...authorStyle }}>{safeAuthor}</div>
        </div>
      )}
    </div>
  );
}

export default Cover;
