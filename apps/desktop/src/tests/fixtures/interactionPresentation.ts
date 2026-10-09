import type { CatalogEntry, CompoundRow, InteractionAnalysisRecord, InteractionContact, PoseInventory } from "../../types/api";

// SYNTHETIC presentation-only data. These geometries and scores are not
// computed scientific results, detector validation, or affinity expectations.
export function contact(index: number, type = "Hydrophobic"): InteractionContact {
  return {
    contact_id: `contact-${index}`, detector_type: type, display_type: type,
    residue: { chain_id: "A", residue_name: "LYS", sequence_number: 123, insertion_code: "" },
    ligand_atom_indices: [index % 2], protein_atom_indices: [index + 10],
    ligand_atom_labels: [`L${index % 2}`], protein_atom_labels: [`P${index + 10}`],
    distance_angstrom: 3 + index / 100, geometry: { distance: 3 + index / 100 },
    ligand_point: { x: index % 2, y: 0, z: 0 }, protein_point: { x: index % 2, y: 3 + index / 100, z: 0 },
  };
}

export const entry: CatalogEntry = {
  catalog_id: "vina_job:synthetic", engine_key: "vina_job", record_id: "synthetic",
  mode: "single_ligand", scoring_family: "vina", backend: null,
  engine_label: "AutoDock Vina · synthetic UI fixture", engine_version: "synthetic",
  executable_sha256: null, device_name: null, reproducibility: {
    status: "not_assessed", protocol: "ankora-reproducibility-v1",
    scope: "synthetic fixture", input_fingerprint_sha256: null, executions: [],
  },
  status: "completed", created_at: "2026-10-09T00:00:00Z", completed_at: "2026-10-09T00:00:01Z",
  receptor_id: "receptor", binding_site_id: "site",
  box: { center_x: 0, center_y: 0, center_z: 0, size_x: 10, size_y: 10, size_z: 10 },
  map_set_id: null, map_set_identity_key: null, library_id: null, filter_run_id: null,
  selection_manifest_sha256: null, ligand_id: "ligand", selected_count: 1, succeeded_count: 1,
  failed_count: 0, canceled_count: 0, best_result_kcal_mol: -1, best_molecule: "Synthetic ligand",
};

export const molecule: CompoundRow = {
  ligand_id: "ligand", source_index: 0, name: "Synthetic ligand", canonical_smiles: "CO",
  molecular_weight_g_mol: 32, status: "completed", failure_code: null,
  best_result_kcal_mol: -1, pose_count: 1, cluster_count: null, top_cluster_runs: null,
};

export const inventory: PoseInventory = {
  catalog_id: entry.catalog_id, ligand_id: molecule.ligand_id, engine_label: entry.engine_label,
  receptor_artifact_id: "receptor-pdb", receptor_content_url: "/synthetic-receptor/content",
  poses: [{
    artifact_id: "pose", kind: "vina_mode", ordinal: 1, label: "Mode 1",
    result_kcal_mol: -1, value_label: "Synthetic UI score", cluster_rank: null, sub_rank: null,
    rmsd_lower_bound_angstrom: null, rmsd_upper_bound_angstrom: null,
    cluster_rmsd_angstrom: null, reference_rmsd_angstrom: null,
    sha256: "a".repeat(64), content_url: "/synthetic-pose/content",
  }],
};

export function analysis(contacts: InteractionContact[]): InteractionAnalysisRecord {
  return {
    analysis_id: "synthetic-analysis", created_at: entry.created_at,
    catalog_id: entry.catalog_id, engine_key: entry.engine_key, record_id: entry.record_id,
    engine_label: entry.engine_label, ligand_id: molecule.ligand_id, ligand_preparation_id: "prep",
    conformer_id: "conformer", conformer_sha256: "b".repeat(64), pose: inventory.poses[0],
    receptor_id: entry.receptor_id, docking_receptor_artifact_id: "receptor-pdbqt",
    docking_receptor_sha256: "c".repeat(64), analysis_receptor_artifact_id: "receptor-pdb",
    analysis_receptor_sha256: "d".repeat(64), analysis_receptor_content_url: inventory.receptor_content_url!,
    detector: { name: "ProLIF", version: "synthetic" },
    profile: { profile_id: "synthetic-ui-only", vicinity_cutoff_angstrom: 6, interactions: [...new Set(contacts.map((item) => item.detector_type))] },
    contacts, ligand_diagram: {
      atoms: [{ atom_index: 0, element: "C", label: "L0", x: 0, y: 0 }, { atom_index: 1, element: "O", label: "L1", x: 1, y: 0 }],
      bonds: [{ begin_atom_index: 0, end_atom_index: 1, order: 1 }],
    },
    warnings: [], provenance: {
      event_id: "synthetic", event_type: "pose_interactions_analyzed", timestamp: entry.created_at,
      input_artifacts: [], output_artifacts: [], tool: { name: "ProLIF", version: "synthetic" },
      parameters: {}, warnings: [], command: null,
    },
  };
}
