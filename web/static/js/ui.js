/* ============================================================
   UI HELPERS — toast, skeleton, modal, focus-trap
   No deps. Window-scoped: window.HMUI
   ============================================================ */

(function () {
  // ---------- TOAST ----------
  function ensureToastRoot() {
    let root = document.getElementById("hm-toast-root");
    if (!root) {
      root = document.createElement("div");
      root.id = "hm-toast-root";
      root.className = "toast-root";
      root.setAttribute("role", "status");
      root.setAttribute("aria-live", "polite");
      document.body.appendChild(root);
    }
    return root;
  }

  function toast(message, variant = "info", timeout = 3500) {
    const root = ensureToastRoot();
    const el = document.createElement("div");
    el.className = `toast toast--${variant}`;
    el.setAttribute("role", "alert");
    el.textContent = message;
    root.appendChild(el);

    const remove = () => {
      el.classList.add("toast--exit");
      el.addEventListener("animationend", () => el.remove(), { once: true });
    };
    window.setTimeout(remove, timeout);
    return remove;
  }

  // ---------- SKELETON ----------
  // Generate skeleton placeholder HTML
  function skeleton({ kind = "text", count = 1 } = {}) {
    const cls = `skeleton skeleton--${kind}`;
    return Array.from({ length: count }, () => `<span class="${cls}"></span>`).join("");
  }

  function setBusy(el, busy = true) {
    if (!el) return;
    if (busy) el.setAttribute("aria-busy", "true");
    else el.removeAttribute("aria-busy");
  }

  // ---------- MODAL ----------
  // Open/close pattern with focus trap and Esc-to-close
  const _modalState = new WeakMap();

  function trapFocus(modalEl, e) {
    const focusables = modalEl.querySelectorAll(
      'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  function openModal(rootEl) {
    if (!rootEl) return;
    rootEl.hidden = false;
    rootEl.removeAttribute("hidden");
    rootEl.classList.remove("hidden");

    const previousActive = document.activeElement;
    _modalState.set(rootEl, { previousActive });

    const dialog = rootEl.querySelector(".modal") || rootEl.firstElementChild;
    if (dialog) {
      dialog.setAttribute("role", "dialog");
      dialog.setAttribute("aria-modal", "true");
      const auto = dialog.querySelector("[autofocus], input, select, textarea, button");
      if (auto) auto.focus();
    }

    const onKey = (e) => {
      if (e.key === "Escape") closeModal(rootEl);
      else if (e.key === "Tab" && dialog) trapFocus(dialog, e);
    };
    rootEl.addEventListener("keydown", onKey);
    _modalState.get(rootEl).onKey = onKey;

    // Click outside to close
    const onBackdrop = (e) => { if (e.target === rootEl) closeModal(rootEl); };
    rootEl.addEventListener("click", onBackdrop);
    _modalState.get(rootEl).onBackdrop = onBackdrop;

    document.body.style.overflow = "hidden";
  }

  function closeModal(rootEl) {
    if (!rootEl) return;
    rootEl.hidden = true;
    rootEl.classList.add("hidden");

    const state = _modalState.get(rootEl);
    if (state) {
      if (state.onKey) rootEl.removeEventListener("keydown", state.onKey);
      if (state.onBackdrop) rootEl.removeEventListener("click", state.onBackdrop);
      if (state.previousActive && typeof state.previousActive.focus === "function") {
        state.previousActive.focus();
      }
      _modalState.delete(rootEl);
    }

    // Restore body scroll only if no modal is open
    const anyOpen = document.querySelector(".modal-root:not([hidden]):not(.hidden)");
    if (!anyOpen) document.body.style.overflow = "";
  }

  // ---------- ANIMATE ON SCROLL (light) ----------
  // Adds .is-in-view when an element enters the viewport once.
  function observeReveal() {
    if (!("IntersectionObserver" in window)) return;
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-in-view");
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.08 });
    document.querySelectorAll("[data-reveal]").forEach((el) => io.observe(el));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", observeReveal);
  } else {
    observeReveal();
  }

  window.HMUI = {
    toast,
    skeleton,
    setBusy,
    openModal,
    closeModal,
  };
})();
