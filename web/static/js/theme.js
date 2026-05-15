/* ============================================================
   THEME TOGGLE — vanilla JS, no deps
   - Persists in localStorage('hm-theme')
   - Honors prefers-color-scheme on first visit
   - Adds .theme-transition class for smooth cross-fade
   ============================================================ */

(function () {
  const STORAGE_KEY = "hm-theme";
  const ROOT = document.documentElement;

  function getStoredTheme() {
    try { return localStorage.getItem(STORAGE_KEY); } catch (_) { return null; }
  }

  function getSystemTheme() {
    return window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: light)").matches
      ? "light" : "dark";
  }

  function applyTheme(theme, animate) {
    if (animate) {
      ROOT.classList.add("theme-transition");
      window.setTimeout(() => ROOT.classList.remove("theme-transition"), 360);
    }
    ROOT.setAttribute("data-theme", theme);
    // Compat: Tailwind dark mode in dashboard.html uses html.dark — keep in sync
    // until the CSS migration is complete and Tailwind is removed.
    if (theme === "dark") ROOT.classList.add("dark");
    else                  ROOT.classList.remove("dark");
    // Update aria-pressed on toggle buttons
    document.querySelectorAll("[data-theme-btn]").forEach((btn) => {
      btn.setAttribute("aria-pressed", btn.dataset.themeBtn === theme ? "true" : "false");
    });
  }

  function setTheme(theme, animate = true) {
    try { localStorage.setItem(STORAGE_KEY, theme); } catch (_) {}
    applyTheme(theme, animate);
  }

  // Init — synchronous so there's no flash
  const initial = getStoredTheme() || getSystemTheme();
  applyTheme(initial, false);

  // Wire toggle buttons on DOM ready
  function wire() {
    document.querySelectorAll("[data-theme-btn]").forEach((btn) => {
      btn.addEventListener("click", () => setTheme(btn.dataset.themeBtn, true));
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }

  // Expose minimal API
  window.HMTheme = {
    get: () => ROOT.getAttribute("data-theme"),
    set: setTheme,
    toggle: () => setTheme(ROOT.getAttribute("data-theme") === "light" ? "dark" : "light", true),
  };
})();
