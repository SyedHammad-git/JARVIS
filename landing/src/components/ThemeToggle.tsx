"use client";

import { useEffect, useSyncExternalStore } from "react";

type Theme = "light" | "dark";
const listeners = new Set<() => void>();

function getTheme(): Theme {
  const saved = window.localStorage.getItem("jarvis-theme");
  if (saved === "light" || saved === "dark") return saved;
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const onStorage = () => listeners.forEach((notify) => notify());
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

export function ThemeToggle() {
  const theme = useSyncExternalStore(subscribe, getTheme, () => "light");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  function toggleTheme() {
    const nextTheme = theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = nextTheme;
    window.localStorage.setItem("jarvis-theme", nextTheme);
    listeners.forEach((notify) => notify());
  }

  return (
    <button
      className="theme-toggle"
      type="button"
      onClick={toggleTheme}
      aria-label={`Switch to ${theme === "light" ? "dark" : "light"} theme`}
      title={`Switch to ${theme === "light" ? "dark" : "light"} theme`}
    >
      <span aria-hidden="true">{theme === "light" ? "☾" : "☀"}</span>
    </button>
  );
}
