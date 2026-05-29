import { Moon, Sun } from "lucide-react";
import { type ReactElement, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";

/**
 * Light/dark theme toggle. The actual class application happens in the
 * inline script in `Layout.astro` (runs before paint so we don't flash
 * the wrong theme); this component just owns the user-facing button and
 * persists the chosen value to `localStorage`.
 *
 * "system" mode follows `prefers-color-scheme`. We collapse the tri-state
 * into a binary toggle for now — the inline script honours "system" if
 * `localStorage["theme"]` is missing or set to "system".
 */
export function ThemeToggle(): ReactElement {
  const [theme, setTheme] = useState<"light" | "dark">("light");

  useEffect(() => {
    const root = document.documentElement;
    const isDark = root.classList.contains("dark");
    setTheme(isDark ? "dark" : "light");
  }, []);

  const flip = (): void => {
    const next = theme === "dark" ? "light" : "dark";
    const root = document.documentElement;
    root.classList.toggle("dark", next === "dark");
    window.localStorage.setItem("theme", next);
    setTheme(next);
  };

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
      onClick={flip}
    >
      {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  );
}

export default ThemeToggle;
