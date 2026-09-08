import { useCallback, useEffect, useRef, useState } from "react";

import { ankoraApi } from "../../api/client";
import type { CampaignHistory, CampaignSummary } from "../../types/api";
import { formatApplicationDateTime, formatScientificNumber } from "../../utils/format";

/**
 * Every campaign a project has run against one receptor and search space.
 *
 * Reconnecting to the most recent campaign is not enough on its own: a project
 * accumulates campaigns - a first attempt, a re-run with more exhaustiveness,
 * one over a different selection - and the scientist has to be able to open an
 * earlier one rather than only the newest.
 *
 * The list carries summaries, never results. A completed campaign record holds
 * every pose of every molecule and is measured in megabytes, so the full record
 * is fetched only for the campaign actually opened.
 */
type CampaignEngine = "autodock_vina" | "autodock4";

interface UseCampaignHistoryOptions {
  engine: CampaignEngine;
  receptorId: string;
  bindingSiteId: string;
}
export function useCampaignHistory({
  engine,
  receptorId,
  bindingSiteId,
}: UseCampaignHistoryOptions) {
  const [campaigns, setCampaigns] = useState<CampaignSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(false);
  const requestRef = useRef(0);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestRef.current += 1;
    };
  }, []);

  const reload = useCallback(async (): Promise<CampaignHistory | null> => {
    const request = requestRef.current + 1;
    requestRef.current = request;
    setLoading(true);
    setError(null);
    try {
      const history = engine === "autodock4"
        ? await ankoraApi.autoDock4CampaignHistory(receptorId, bindingSiteId)
        : await ankoraApi.vinaCampaignHistory(receptorId, bindingSiteId);
      if (mountedRef.current && requestRef.current === request) {
        setCampaigns(history.campaigns);
      }
      return history;
    } catch (reason: unknown) {
      if (mountedRef.current && requestRef.current === request) {
        setCampaigns([]);
        setError(
          reason instanceof Error ? reason.message : "Campaign history is unavailable.",
        );
      }
      return null;
    } finally {
      if (mountedRef.current && requestRef.current === request) {
        setLoading(false);
      }
    }
  }, [engine, receptorId, bindingSiteId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { campaigns, loading, error, reload };
}

interface CampaignHistoryPanelProps {
  engine: CampaignEngine;
  campaigns: CampaignSummary[];
  loading: boolean;
  error: string | null;
  /** The campaign currently open in the workspace, if any. */
  activeBatchId: string | null;
  /** The selection applied right now, so a campaign over another one is flagged. */
  currentFilterRunId: string | null;
  /** True while a record is being fetched, so the list cannot be double-clicked. */
  opening: boolean;
  onOpen: (batchId: string) => void;
  onRefresh: () => void;
}

export function CampaignHistoryPanel({
  engine,
  campaigns,
  loading,
  error,
  activeBatchId,
  currentFilterRunId,
  opening,
  onOpen,
  onRefresh,
}: CampaignHistoryPanelProps) {
  const unit = engine === "autodock4" ? "energy" : "score";
  return (
    <section className="receptor-section">
      <div className="filter-heading">
        <span>Campaign history</span>
        <button type="button" onClick={onRefresh} disabled={loading}>
          {loading ? "Reading…" : "Refresh"}
        </button>
      </div>
      {error ? (
        <p className="field-note">{error}</p>
      ) : campaigns.length === 0 ? (
        <p className="field-note">
          {loading
            ? "Reading the campaigns saved for this receptor and search space…"
            : "No campaign has been saved for this receptor and search space yet."}
        </p>
      ) : (
        <>
          <p className="field-note">
            {campaigns.length === 1
              ? "One campaign is saved for this receptor and search space."
              : `${campaigns.length} campaigns are saved for this receptor and search space.`}{" "}
            Opening one loads its own results; it does not re-run anything.
          </p>
          <div className="campaign-history-list" role="group" aria-label="Saved campaigns">
            {campaigns.map((campaign) => {
              const isActive = campaign.batch_id === activeBatchId;
              const otherSelection =
                currentFilterRunId !== null &&
                campaign.filter_run_id !== currentFilterRunId;
              return (
                <button
                  key={campaign.batch_id}
                  type="button"
                  className={isActive ? "campaign-history-entry selected" : "campaign-history-entry"}
                  onClick={() => onOpen(campaign.batch_id)}
                  disabled={opening || isActive}
                  aria-current={isActive ? "true" : undefined}
                >
                  <span className="campaign-history-when">
                    <b>{formatApplicationDateTime(campaign.created_at)}</b>
                    <small>
                      {campaign.is_running ? "running" : campaign.status.replaceAll("_", " ")}
                      {" · "}
                      {campaign.succeeded_count}/{campaign.selected_count} docked
                    </small>
                  </span>
                  <span className="campaign-history-best">
                    {campaign.best_result_kcal_mol === null ? (
                      <b>—</b>
                    ) : (
                      <>
                        <b>{formatScientificNumber(campaign.best_result_kcal_mol, 2)}</b>
                        <small>best {unit} kcal/mol</small>
                      </>
                    )}
                  </span>
                  {otherSelection || !campaign.same_site_record ? (
                    <span className="campaign-history-flags">
                      {otherSelection ? <em>different selection</em> : null}
                      {!campaign.same_site_record ? <em>same box, other site record</em> : null}
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>
        </>
      )}
    </section>
  );
}
