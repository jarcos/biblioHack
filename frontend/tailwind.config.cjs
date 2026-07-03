/** @type {import('tailwindcss').Config} */
/*
 * Tailwind config — bridge layer between our CSS-variable tokens
 * (defined in `src/styles/global.css`) and Tailwind utility names.
 *
 * The convention is: every semantic color in the design system has a
 * matching --token defined under :root (light) and .dark (dark), and
 * this file exposes it as a Tailwind class like `bg-background`,
 * `text-muted-foreground`, etc. Flip the `dark` class on <html> to
 * toggle themes.
 */
module.exports = {
    darkMode: ["class"],
    content: ["./src/**/*.{astro,html,js,jsx,md,mdx,ts,tsx}"],
    theme: {
        container: {
            center: true,
            padding: "1.5rem",
            screens: {
                "2xl": "72rem",
            },
        },
        extend: {
            fontFamily: {
                sans: [
                    '"IBM Plex Sans"',
                    "ui-sans-serif",
                    "system-ui",
                    "-apple-system",
                    "Segoe UI",
                    "Roboto",
                    "sans-serif",
                ],
                serif: ["Spectral", "ui-serif", "Georgia", '"Times New Roman"', "serif"],
                mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
            },
            colors: {
                border: "hsl(var(--border))",
                input: "hsl(var(--input))",
                ring: "hsl(var(--ring))",
                background: {
                    DEFAULT: "hsl(var(--background))",
                    2: "hsl(var(--background-2))",
                },
                foreground: "hsl(var(--foreground))",
                // Tinta 3 — tertiary text (eyebrows, meta, counters)
                faint: "hsl(var(--faint))",
                primary: {
                    DEFAULT: "hsl(var(--primary))",
                    foreground: "hsl(var(--primary-foreground))",
                },
                secondary: {
                    DEFAULT: "hsl(var(--secondary))",
                    foreground: "hsl(var(--secondary-foreground))",
                },
                destructive: {
                    DEFAULT: "hsl(var(--destructive))",
                    foreground: "hsl(var(--destructive-foreground))",
                    soft: "hsl(var(--destructive-soft))",
                    "soft-foreground": "hsl(var(--destructive-soft-foreground))",
                },
                // Verde suave — availability-positive surfaces ("En tu biblioteca")
                brand: {
                    soft: "hsl(var(--brand-soft))",
                    "soft-foreground": "hsl(var(--brand-soft-foreground))",
                },
                // Ocre — the measured accent (affinity, numerals, "En la red")
                ocre: {
                    DEFAULT: "hsl(var(--ocre))",
                    soft: "hsl(var(--ocre-soft))",
                    "soft-foreground": "hsl(var(--ocre-soft-foreground))",
                },
                muted: {
                    DEFAULT: "hsl(var(--muted))",
                    foreground: "hsl(var(--muted-foreground))",
                },
                accent: {
                    DEFAULT: "hsl(var(--accent))",
                    foreground: "hsl(var(--accent-foreground))",
                },
                popover: {
                    DEFAULT: "hsl(var(--popover))",
                    foreground: "hsl(var(--popover-foreground))",
                },
                card: {
                    DEFAULT: "hsl(var(--card))",
                    foreground: "hsl(var(--card-foreground))",
                },
                // Availability status colors, used by Badge variants for the
                // M2 AvailabilityStatus enum (available/loaned/etc.).
                status: {
                    available: "hsl(var(--status-available))",
                    loaned: "hsl(var(--status-loaned))",
                    reserved: "hsl(var(--status-reserved))",
                    unavailable: "hsl(var(--status-unavailable))",
                    unknown: "hsl(var(--status-unknown))",
                },
            },
            borderRadius: {
                lg: "var(--radius)",
                md: "calc(var(--radius) - 2px)",
                sm: "calc(var(--radius) - 4px)",
            },
            boxShadow: {
                // Design `--shadow` — paper card lifting off the desk
                card: "var(--shadow-card)",
                // Book-cover drop shadow used across shelves/grids
                cover: "var(--shadow-cover)",
            },
            keyframes: {
                "accordion-down": {
                    from: { height: "0" },
                    to: { height: "var(--radix-accordion-content-height)" },
                },
                "accordion-up": {
                    from: { height: "var(--radix-accordion-content-height)" },
                    to: { height: "0" },
                },
            },
            animation: {
                "accordion-down": "accordion-down 0.2s ease-out",
                "accordion-up": "accordion-up 0.2s ease-out",
            },
        },
    },
    plugins: [require("tailwindcss-animate")],
};
