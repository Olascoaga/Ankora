import { useState } from "react";

import { ankoraApi } from "../../api/client";
import type { GninaPackStatus, ToolStatus } from "../../types/api";
import { chooseGninaPackArchive, gninaPackChooserAvailable } from "./chooseGninaPack";

interface GninaOfflinePackControlProps {
  gnina: ToolStatus | null | undefined;
  disabled?: boolean;
  onToolsRefresh?: () => Promise<void> | void;
}

export function GninaOfflinePackControl({
  gnina,
  disabled = false,
  onToolsRefresh,
}: GninaOfflinePackControlProps) {
  const [importing, setImporting] = useState(false);
  const [importedPack, setImportedPack] = useState<GninaPackStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const chooserAvailable = gninaPackChooserAvailable();

  // When GNINA is already available (and was not just imported in this view),
  // keep the workspace uncluttered.
  if (gnina?.available && !importedPack && !importing && !error) {
    return null;
  }

  async function handleImport() {
    if (disabled || importing || !chooserAvailable) return;
    setError(null);
    let archivePath: string | null = null;
    try {
      archivePath = await chooseGninaPackArchive();
    } catch (reason: unknown) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The file chooser could not be opened.",
      );
      return;
    }
    if (!archivePath) return;

    setImporting(true);
    try {
      const status = await ankoraApi.importGninaPack({ archive_path: archivePath });
      setImportedPack(status);
      await onToolsRefresh?.();
    } catch (reason: unknown) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The offline GNINA pack could not be verified and installed.",
      );
    } finally {
      setImporting(false);
    }
  }

  return (
    <div className="gnina-pack-control" aria-label="Offline GNINA pack installer">
      {!gnina?.available && !importedPack?.installed ? (
        <p className="field-note">
          Packaged Linux installs keep the core installer compact by shipping GNINA 1.3.3 and its
          17 CUDA 12.8 / cuDNN 9.25 runtime libraries as a separate offline pack (
          <code>Ankora_0.1.0_gnina-cuda12-pack.tar.zst</code>). Importing verifies every SHA-256
          digest and installs into Ankora&apos;s user data folder without <code>sudo</code> or
          terminal commands, under the bundled NVIDIA CUDA/cuDNN runtime terms and GNINA GPL-2.0
          source notice.
        </p>
      ) : null}
      <button
        type="button"
        className="secondary-action"
        disabled={disabled || importing || !chooserAvailable}
        title={
          !chooserAvailable
            ? "Offline GNINA pack import requires the native file dialog in the Ankora desktop app."
            : undefined
        }
        onClick={() => void handleImport()}
      >
        {importing
          ? "Verifying & installing GNINA pack…"
          : importedPack?.installed || gnina?.available
            ? "Reinstall offline GNINA pack…"
            : "Import offline GNINA pack…"}
      </button>
      {importing ? (
        <p className="field-note" role="status">
          Streaming Zstandard archive and verifying cryptographic SHA-256 digests of GNINA 1.3.3
          and 17 CUDA/cuDNN shared libraries…
        </p>
      ) : null}
      {importedPack?.installed ? (
        <div className="state-resolved-note" role="status">
          <strong>GNINA {importedPack.gnina_version} offline pack verified</strong>
          <small>
            {importedPack.shared_library_count} isolated CUDA 12.8 / cuDNN 9.25 libraries ready
            {importedPack.executable_sha256
              ? ` · SHA-256 ${importedPack.executable_sha256.slice(0, 12)}…`
              : ""}
          </small>
        </div>
      ) : null}
      {error ? (
        <div className="structure-error" role="alert">
          {error}
        </div>
      ) : null}
    </div>
  );
}
