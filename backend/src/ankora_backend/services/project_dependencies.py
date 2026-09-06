"""Rebuildable project dependency graph and explicit stale propagation.

The graph is derived from immutable record files.  Only the scientist's stale
decisions live in mutable workspace metadata outside the project evidence tree;
marking a node never edits or deletes the record that made it.
"""

from __future__ import annotations

import json
import os
import threading
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.domain.project_context import current_project_id, resolve_project_root
from ankora_backend.schemas.projects import (
    DependencyEdge,
    DependencyNode,
    DependencyNodeKind,
    MarkArtifactStaleResponse,
    ProjectDependencyGraph,
)

_STAGE = "project_dependencies"
_LOCK = threading.RLock()
_REFERENCE_KEYS = {
    "analysis_id",
    "analysis_receptor_artifact_id",
    "binding_site_id",
    "catalog_id",
    "chemical_state_id",
    "conformer_id",
    "docking_receptor_artifact_id",
    "filter_run_id",
    "interaction_analysis_id",
    "library_id",
    "ligand_id",
    "ligand_preparation_id",
    "map_set_id",
    "parent_binding_site_id",
    "parent_compound_id",
    "parent_state_id",
    "pose_artifact_id",
    "preparation_id",
    "receptor_id",
    "receptor_output_artifact_id",
    "record_id",
    "reference_ligand_id",
    "report_id",
    "selection_manifest_artifact_id",
    "source_artifact_id",
    "source_id",
    "source_output_artifact_id",
    "source_structure_id",
    "state_id",
}
_OUTPUT_OWNER_KINDS = {
    DependencyNodeKind.STRUCTURE,
    DependencyNodeKind.RECEPTOR,
    DependencyNodeKind.LIGAND,
    DependencyNodeKind.LIGAND_FILTER,
    DependencyNodeKind.CHEMICAL_STATE,
    DependencyNodeKind.CONFORMER,
    DependencyNodeKind.LIGAND_PREPARATION,
    DependencyNodeKind.AUTOGRID_MAP_SET,
    DependencyNodeKind.DOCKING_CAMPAIGN,
}


@dataclass(slots=True)
class _Candidate:
    node_id: str
    kind: DependencyNodeKind
    label: str
    path: Path
    raw: dict[str, Any]
    parent_refs: set[str]
    aliases: set[str]
    intrinsic_stale: bool


class ProjectDependencyService:
    def __init__(self, *, root: Path, project_id: str | None = None) -> None:
        self._root = root.resolve()
        self._project_id = project_id or current_project_id()
        self._project_root = resolve_project_root(self._root, self._project_id)
        self._state_path = (
            self._root / "workspace" / "stale" / f"{self._project_id}.json"
        ).resolve()

    @classmethod
    def from_environment(cls) -> ProjectDependencyService:
        configured = os.getenv("ANKORA_DATA_DIR")
        root = Path(configured) if configured else Path.cwd() / ".ankora-data"
        return cls(root=root)

    def graph(self, *, offset: int = 0, limit: int = 100) -> ProjectDependencyGraph:
        if offset < 0 or limit < 1 or limit > 500:
            raise AnkoraDomainError(
                code="PROJECT_GRAPH_PAGE_INVALID",
                stage=_STAGE,
                message="Dependency pages require offset >= 0 and limit between 1 and 500.",
                status_code=422,
                details={"offset": offset, "limit": limit},
            )
        return self._graph(offset=offset, limit=limit)

    def _graph(self, *, offset: int, limit: int) -> ProjectDependencyGraph:
        candidates = self._candidates()
        aliases = {
            alias: item.node_id
            for item in candidates
            for alias in {item.node_id, *item.aliases}
        }
        edge_pairs: set[tuple[str, str]] = set()
        unresolved: dict[str, set[str]] = {}
        for item in candidates:
            for reference in item.parent_refs:
                parent = aliases.get(reference)
                if parent is None:
                    unresolved.setdefault(item.node_id, set()).add(reference)
                elif parent != item.node_id:
                    edge_pairs.add((parent, item.node_id))

        reasons = self._stale_reasons()
        for item in candidates:
            if item.intrinsic_stale:
                reasons.setdefault(item.node_id, []).append(
                    "The immutable record already declares this artifact stale."
                )
        children: dict[str, set[str]] = {}
        for parent, child in edge_pairs:
            children.setdefault(parent, set()).add(child)
        stale_ids = set(reasons)
        queue = deque(sorted(stale_ids))
        while queue:
            parent = queue.popleft()
            for child in sorted(children.get(parent, ())):
                reason = f"Depends on stale artifact {parent}."
                reasons.setdefault(child, []).append(reason)
                if child not in stale_ids:
                    stale_ids.add(child)
                    queue.append(child)

        ordered = sorted(candidates, key=lambda item: (item.kind.value, item.label, item.node_id))
        selected = ordered[offset : offset + limit]
        selected_ids = {item.node_id for item in selected}
        nodes = [
            DependencyNode(
                node_id=item.node_id,
                kind=item.kind,
                label=item.label,
                relative_path=item.path.relative_to(self._project_root).as_posix(),
                parent_ids=sorted(
                    parent for parent, child in edge_pairs if child == item.node_id
                ),
                unresolved_parent_ids=sorted(unresolved.get(item.node_id, set())),
                stale=item.node_id in stale_ids,
                stale_reasons=list(dict.fromkeys(reasons.get(item.node_id, []))),
            )
            for item in selected
        ]
        edges = [
            DependencyEdge(parent_id=parent, child_id=child)
            for parent, child in sorted(edge_pairs)
            if child in selected_ids
        ]
        return ProjectDependencyGraph(
            project_id=self._project_id,
            generated_at=datetime.now(UTC),
            nodes=nodes,
            edges=edges,
            total_nodes=len(ordered),
            offset=offset,
            limit=limit,
            stale_count=len(stale_ids),
            unresolved_reference_count=sum(len(items) for items in unresolved.values()),
        )

    def mark_stale(self, node_id: str, reason: str) -> MarkArtifactStaleResponse:
        with _LOCK:
            candidates = self._candidates()
            all_ids = {item.node_id for item in candidates}
            if node_id not in all_ids:
                raise AnkoraDomainError(
                    code="PROJECT_DEPENDENCY_NOT_FOUND",
                    stage=_STAGE,
                    message="The requested artifact is not present in this project graph.",
                    status_code=404,
                    details={"node_id": node_id},
                )
            before = self._graph(offset=0, limit=max(1, len(candidates)))
            state = self._read_state()
            markers = state.setdefault("markers", {})
            markers[node_id] = {
                "reason": reason,
                "marked_at": datetime.now(UTC).isoformat(),
            }
            self._write_state(state)
            after = self._graph(offset=0, limit=max(1, len(candidates)))
            before_stale = {item.node_id for item in before.nodes if item.stale}
            after_stale = {item.node_id for item in after.nodes if item.stale}
            return MarkArtifactStaleResponse(
                marked_node_id=node_id,
                affected_node_ids=sorted(after_stale - before_stale),
            )

    def _candidates(self) -> list[_Candidate]:
        if not self._project_root.is_dir():
            return []
        candidates: list[_Candidate] = []
        for path in self._record_paths():
            raw = _read_object(path)
            if raw is None:
                continue
            kind = _kind_for(path.relative_to(self._project_root).parts)
            node_id = path.parent.name
            references = set(_references(raw))
            references.discard(node_id)
            aliases = set(_artifact_aliases(raw)) if kind in _OUTPUT_OWNER_KINDS else set()
            aliases.discard(node_id)
            candidates.append(
                _Candidate(
                    node_id=node_id,
                    kind=kind,
                    label=_label(raw, node_id, kind),
                    path=path,
                    raw=raw,
                    parent_refs=references,
                    aliases=aliases,
                    intrinsic_stale=bool(raw.get("stale", False)),
                )
            )
        candidates.extend(self._export_candidates())
        # One record is authoritative for one storage identity. Evidence copied
        # inside an export and Trash were excluded before this deduplication.
        return list({item.node_id: item for item in candidates}.values())

    def _record_paths(self) -> Iterable[Path]:
        for path in sorted(self._project_root.rglob("record.json")):
            relative = path.relative_to(self._project_root).parts
            if relative[0] in {"trash", "runtime", "exports"}:
                continue
            yield path

    def _export_candidates(self) -> list[_Candidate]:
        found: list[_Candidate] = []
        patterns = (
            ("*/manifest.json", DependencyNodeKind.EXPORT),
            ("figures/*/figure.json", DependencyNodeKind.EXPORT),
            ("pose_complexes/*/complex.json", DependencyNodeKind.EXPORT),
        )
        exports = self._project_root / "exports"
        for pattern, kind in patterns:
            for path in exports.glob(pattern):
                raw = _read_object(path)
                if raw is None:
                    continue
                node_id = path.parent.name
                references = set(_references(raw))
                references.discard(node_id)
                found.append(
                    _Candidate(
                        node_id=node_id,
                        kind=kind,
                        label=_label(raw, node_id, kind),
                        path=path,
                        raw=raw,
                        parent_refs=references,
                        aliases=set(),
                        intrinsic_stale=False,
                    )
                )
        return found

    def _stale_reasons(self) -> dict[str, list[str]]:
        state = self._read_state()
        markers = state.get("markers")
        if not isinstance(markers, dict):
            return {}
        reasons: dict[str, list[str]] = {}
        for node_id, marker in markers.items():
            if isinstance(node_id, str) and isinstance(marker, dict):
                reason = marker.get("reason")
                if isinstance(reason, str) and reason:
                    reasons[node_id] = [reason]
        return reasons

    def _read_state(self) -> dict[str, Any]:
        try:
            loaded = json.loads(self._state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"version": 1, "project_id": self._project_id, "markers": {}}
        except (OSError, ValueError) as error:
            raise AnkoraDomainError(
                code="PROJECT_STALE_STATE_INVALID",
                stage=_STAGE,
                message="The project's stale-state metadata could not be read safely.",
                status_code=500,
                recoverable=False,
            ) from error
        if not isinstance(loaded, dict) or loaded.get("project_id") != self._project_id:
            raise AnkoraDomainError(
                code="PROJECT_STALE_STATE_INVALID",
                stage=_STAGE,
                message="The project's stale-state metadata has the wrong identity.",
                status_code=500,
                recoverable=False,
            )
        return loaded

    def _write_state(self, state: dict[str, Any]) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._state_path.with_suffix(f".{uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(state, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._state_path)
        finally:
            temporary.unlink(missing_ok=True)


def _kind_for(parts: tuple[str, ...]) -> DependencyNodeKind:
    if parts[:2] == ("original", "structures"):
        return DependencyNodeKind.STRUCTURE
    if parts[:2] == ("original", "ligands"):
        return DependencyNodeKind.LIGAND
    if parts[:2] == ("original", "ligand_libraries"):
        return DependencyNodeKind.LIGAND_LIBRARY
    if parts[:2] == ("derived", "receptors"):
        return DependencyNodeKind.RECEPTOR
    if parts[:2] == ("derived", "binding_sites"):
        return DependencyNodeKind.BINDING_SITE
    if parts[:2] == ("derived", "pocket_detection"):
        return DependencyNodeKind.POCKET_DETECTION
    if parts[:2] == ("derived", "autogrid_maps"):
        return DependencyNodeKind.AUTOGRID_MAP_SET
    if "filter_runs" in parts:
        return DependencyNodeKind.LIGAND_FILTER
    if "states" in parts:
        return DependencyNodeKind.CHEMICAL_STATE
    if "conformers" in parts:
        return DependencyNodeKind.CONFORMER
    if "preparations" in parts:
        return DependencyNodeKind.LIGAND_PREPARATION
    if parts and parts[0] == "results":
        return DependencyNodeKind.DOCKING_CAMPAIGN
    if parts[:2] == ("validation", "redocking"):
        return DependencyNodeKind.VALIDATION
    if parts[:2] == ("analysis", "pose_interactions"):
        return DependencyNodeKind.POSE_ANALYSIS
    return DependencyNodeKind.UNKNOWN


def _read_object(path: Path) -> dict[str, Any] | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _references(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _REFERENCE_KEYS and isinstance(item, str) and item:
                yield _normalized_reference(item)
            yield from _references(item)
    elif isinstance(value, list):
        for item in value:
            yield from _references(item)


def _artifact_aliases(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        artifact_id = value.get("artifact_id")
        if isinstance(artifact_id, str) and artifact_id:
            yield artifact_id
        yield from (
            alias
            for item in value.values()
            for alias in _artifact_aliases(item)
        )
    elif isinstance(value, list):
        yield from (alias for item in value for alias in _artifact_aliases(item))


def _normalized_reference(value: str) -> str:
    suffix = value.rsplit(":", maxsplit=1)[-1]
    try:
        return str(UUID(suffix))
    except ValueError:
        return value


def _label(raw: dict[str, Any], node_id: str, kind: DependencyNodeKind) -> str:
    for value in (
        raw.get("molecule_name"),
        raw.get("name"),
        (raw.get("metadata") or {}).get("entry_id")
        if isinstance(raw.get("metadata"), dict)
        else None,
        (raw.get("artifact") or {}).get("filename")
        if isinstance(raw.get("artifact"), dict)
        else None,
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"{kind.value.replace('_', ' ').title()} · {node_id[:8]}"
