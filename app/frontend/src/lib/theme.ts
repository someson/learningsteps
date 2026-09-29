import { useEffect, useState } from "react"

export type Theme = "light" | "dark"

// Light is the default. Only an explicit choice with the toggle is stored,
// under "ui-theme" (the older "theme" key also held values saved from the
// system preference, so it is no longer read).
const STORAGE_KEY = "ui-theme"

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() =>
    document.documentElement.classList.contains("dark") ? "dark" : "light"
  )

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark")
  }, [theme])

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark"
    setTheme(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // Storage may be blocked; the theme still applies for this visit.
    }
  }

  return { theme, toggle }
}
