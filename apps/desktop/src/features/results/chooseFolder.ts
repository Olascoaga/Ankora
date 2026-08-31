import { isTauri } from "@tauri-apps/api/core";

/**
 * Asking Windows where an exported artifact should go.
 *
 * The desktop shell is granted `dialog:allow-open` and nothing else, so this
 * can put a folder chooser on screen and read back the path the scientist
 * picked — it cannot read, write or list anything. The backend remains the
 * only thing that touches a file, which is what keeps a chosen folder from
 * becoming a general filesystem capability in the page.
 *
 * Running in a plain browser (the dev server) there is no shell to ask, and
 * the caller is told so rather than shown a button that does nothing.
 */

const REMEMBERED = "ankora.exports.destination";
const LEGACY_FIGURE_DESTINATION = "ankora.figures.destination";

export function folderChooserAvailable(): boolean {
  try {
    return isTauri();
  } catch {
    return false;
  }
}

/** The folder the scientist picked, or null if they dismissed the dialog. */
export async function chooseFolder(title: string): Promise<string | null> {
  // Imported only once it is going to be used: the web build should never pull
  // the plugin in, and the module throws on import outside the shell.
  const { open } = await import("@tauri-apps/plugin-dialog");
  const picked = await open({ directory: true, multiple: false, title });
  return typeof picked === "string" ? picked : null;
}

/**
 * The last folder used, so the next figure or coordinate file lands beside it.
 *
 * A per-machine convenience, not a project setting: it says nothing about the
 * science and is never written into a record.
 */
export function rememberedFolder(): string | null {
  try {
    const current = window.localStorage.getItem(REMEMBERED);
    if (current) return current;
    const legacy = window.localStorage.getItem(LEGACY_FIGURE_DESTINATION);
    if (legacy) {
      window.localStorage.setItem(REMEMBERED, legacy);
      window.localStorage.removeItem(LEGACY_FIGURE_DESTINATION);
    }
    return legacy;
  } catch {
    return null;
  }
}

export function rememberFolder(folder: string | null): void {
  try {
    if (folder) window.localStorage.setItem(REMEMBERED, folder);
    else window.localStorage.removeItem(REMEMBERED);
    window.localStorage.removeItem(LEGACY_FIGURE_DESTINATION);
  } catch {
    // A browser with site data blocked still exports; it just forgets.
  }
}
