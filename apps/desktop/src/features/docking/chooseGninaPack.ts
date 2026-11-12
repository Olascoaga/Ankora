import { isTauri } from "@tauri-apps/api/core";

/**
 * Native file picker for the offline Linux GNINA 1.3.3 + CUDA 12 / cuDNN 9 pack.
 *
 * Uses the existing `dialog:allow-open` Tauri capability so the page never
 * receives filesystem access: it hands only the chosen local path string to
 * the localhost FastAPI backend, which verifies every byte and SHA-256 digest
 * before installing under Ankora's isolated toolchains directory.
 */

export function gninaPackChooserAvailable(): boolean {
  try {
    return isTauri();
  } catch {
    return false;
  }
}

export async function chooseGninaPackArchive(): Promise<string | null> {
  const { open } = await import("@tauri-apps/plugin-dialog");
  const picked = await open({
    directory: false,
    multiple: false,
    title: "Select Ankora Offline GNINA Pack (.tar.zst)",
    filters: [
      {
        name: "Ankora Offline GNINA Pack",
        extensions: ["zst", "tzst", "part01", "part02", "gz"],
      },
    ],
  });
  return typeof picked === "string" ? picked : null;
}
