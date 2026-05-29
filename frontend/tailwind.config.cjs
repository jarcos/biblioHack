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
                    '"Inter Variable"',
                    "ui-sans-serif",
                    "system-ui",
                    "-apple-system",
                    "Segoe UI",
                    "Roboto",
                    "sans-serif",
                ],
                serif: [
                    '"Source Serif 4 Variable"',
                    "ui-serif",
                    "Georgia",
                    '"Times New Roman"',
                    "serif",
                ],
            },
            colors: {
                border: "hsl(var(--border))",
                input: "hsl(var(--input))",
                ring: "hsl(var(--ring))",
                background: "hsl(var(--background))",
                foreground: "hsl(var(--foreground))",
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
