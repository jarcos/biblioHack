// @ts-check
import { defineConfig } from "astro/config";
import react from "@astrojs/react";
import tailwind from "@astrojs/tailwind";

// https://astro.build/config
export default defineConfig({
    integrations: [
        react(),
        tailwind({
            // We import the global stylesheet manually in Layout.astro
            applyBaseStyles: false,
        }),
    ],
    server: {
        host: "0.0.0.0",
        port: 4321,
    },
    vite: {
        server: {
            watch: {
                // Avoid watching the .venv when running Astro from a checkout that
                // also has the Python backend installed locally.
                ignored: ["**/.venv/**", "**/node_modules/**", "**/dist/**"],
            },
        },
    },
});
