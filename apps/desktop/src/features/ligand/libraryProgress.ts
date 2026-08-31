export interface LigandLibraryStatusSummary {
  total: number;
  terminal: number;
  prepared: number;
  notReady: number;
}

const TERMINAL_BATCH_STATUSES = new Set([
  "excluded",
  "failed",
  "minimized",
  "nonconverged",
  "prepared",
]);

export function isTerminalLigandBatchStatus(status: string | undefined): boolean {
  return status !== undefined && TERMINAL_BATCH_STATUSES.has(status);
}

export function summarizeLigandLibraryStatus(
  selectedLigandIds: string[],
  statusForLigand: (ligandId: string) => string | undefined,
): LigandLibraryStatusSummary {
  let terminal = 0;
  let prepared = 0;

  for (const ligandId of selectedLigandIds) {
    const status = statusForLigand(ligandId);
    if (isTerminalLigandBatchStatus(status)) terminal += 1;
    if (status === "prepared") prepared += 1;
  }

  return {
    total: selectedLigandIds.length,
    terminal,
    prepared,
    notReady: terminal - prepared,
  };
}

export function isLigandLibraryStageComplete(
  status: LigandLibraryStatusSummary | null,
): boolean {
  return status !== null && status.total > 0 && status.terminal === status.total;
}
