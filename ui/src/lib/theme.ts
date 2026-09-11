import { useEffect } from "react";

/**
 * The operational control-center build is light-only. Some older pages still
 * carry Tailwind `dark:` variants; if a legacy `dark` preference lingered in
 * localStorage those variants activated and produced unreadable dark-on-dark
 * boxes. This hook hard-pins light: it strips the `dark` class and clears the
 * stored preference on mount.
 */
export function useLightTheme() {
  useEffect(() => {
    document.documentElement.classList.remove("dark");
    try {
      window.localStorage.removeItem("alpr-theme");
    } catch {
      /* ignore */
    }
  }, []);
}
