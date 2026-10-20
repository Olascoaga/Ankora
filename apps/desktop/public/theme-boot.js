// Runs before the first paint: the window opens on the scientist's own theme,
// so the startup screen is the first thing drawn, with no frame of another.
// The workbench still validates the stored value and corrects it if needed.
(function () {
  var theme = null;
  try {
    theme = window.localStorage.getItem("ankora-theme");
  } catch (error) {
    // Restricted WebViews may refuse storage; the default theme stays.
  }
  if (theme && /^[a-z][a-z-]{0,31}$/.test(theme)) {
    document.documentElement.setAttribute("data-theme", theme);
  }
})();
