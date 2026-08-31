import type { HealthResponse, StructureRecord, SystemResponse, ToolsResponse } from "../types/api";

export type ConnectionStatus = "checking" | "connected" | "disconnected";

export interface ApplicationState {
  connection: ConnectionStatus;
  health: HealthResponse | null;
  system: SystemResponse | null;
  tools: ToolsResponse | null;
  error: string | null;
  structure: StructureRecord | null;
  structureOperation: "idle" | "loading";
  structureError: string | null;
}

export function createInitialApplicationState(): ApplicationState {
  return {
    connection: "checking",
    health: null,
    system: null,
    tools: null,
    error: null,
    structure: null,
    structureOperation: "idle",
    structureError: null,
  };
}
