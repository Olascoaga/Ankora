"""Explicit opt-in PubChem PUG-REST & ChEMBL REST analog similarity adapters (ADR-033 §5).

Strictly opt-in:
- Never invoked automatically or as a fallback from offline search.
- Fails closed with 422 `ANALOG_EXTERNAL_CONSENT_REQUIRED` unless cryptographic consent
  (`consent_payload_sha256 == sha256(f"{provider}:{query_canonical_smiles}")`) and
  `acknowledge_external_transmission=True` are verified BEFORE creating any HTTP client.
- Enforces 1 concurrent request, <= 1 req/s client throttle, <= 500 candidates, <= 10 MiB
  cumulative response size, <= 2 retries honoring Retry-After, immutable raw response
  archiving, and mandatory local RDKit Morgan ECFP4 Tanimoto recalculation.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from importlib import import_module
from typing import Any, Literal

import httpx

from ankora_backend.adapters.chemistry.analog_similarity import (
    build_search_representation,
    rdkit_version_string,
)
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.analog_expansion import (
    MAX_ONLINE_CANDIDATES,
    MAX_ONLINE_RESPONSE_BYTES,
    AnalogCandidateRole,
    AnalogFingerprintProfile,
    AnalogSearchHit,
    ExternalProviderEvidence,
    ExternalTransmissionConsent,
)
from ankora_backend.schemas.warnings import StructuredWarning, WarningCode

Chem: Any = import_module("rdkit.Chem")
DataStructs: Any = import_module("rdkit.DataStructs")
Descriptors: Any = import_module("rdkit.Chem.Descriptors")
Lipinski: Any = import_module("rdkit.Chem.Lipinski")
rdFingerprintGenerator: Any = import_module("rdkit.Chem.rdFingerprintGenerator")

_STAGE = "analog_external_provider"
_PUBCHEM_ENDPOINT = (
    "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/fastsimilarity_2d/smiles/"
    "property/SMILES,ConnectivitySMILES,Title/JSON"
)
_CHEMBL_BASE = "https://www.ebi.ac.uk/chembl/api/data/similarity"
_MAX_RETRIES = 2
_MAX_RETRY_AFTER_SEC = 10.0
_MIN_REQUEST_INTERVAL_SEC = 1.0

_RATE_LOCK = threading.Lock()
_LAST_REQUEST_AT: dict[str, float] = {}


@dataclass(frozen=True, slots=True)
class _RawCandidate:
    provider_compound_id: str
    identifier: str
    smiles: str
    provider_similarity: float | None


@dataclass(frozen=True, slots=True)
class OnlineSimilarityResult:
    query_canonical_isomeric_smiles: str
    query_search_smiles: str
    rdkit_version: str
    total_evaluated: int
    invalid_skipped: int
    truncated_by_top_k: bool
    hits: list[AnalogSearchHit]
    external_evidence: ExternalProviderEvidence
    raw_response_bytes: bytes
    warnings: list[StructuredWarning]


def _error(
    code: str,
    message: str,
    *,
    status_code: int = 422,
    details: dict[str, object] | None = None,
) -> AnkoraDomainError:
    return AnkoraDomainError(
        code=code,
        stage=_STAGE,
        message=message,
        status_code=status_code,
        details=details or {},
    )


def _throttle_provider(provider: str, sleep_fn: Callable[[float], None]) -> None:
    """Enforce 1 concurrent request and <= 1 req/s per provider (ADR-033 §5)."""
    now = time.monotonic()
    last = _LAST_REQUEST_AT.get(provider)
    if last is not None:
        wait = _MIN_REQUEST_INTERVAL_SEC - (now - last)
        if wait > 0.0:
            sleep_fn(wait)
    _LAST_REQUEST_AT[provider] = time.monotonic()


def _send_bounded_request(
    *,
    client: httpx.Client,
    provider: str,
    method: Literal["GET", "POST"],
    url: str,
    params: dict[str, object] | None = None,
    data: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[httpx.Response, list[int]]:
    status_codes: list[int] = []
    for attempt in range(_MAX_RETRIES + 1):
        with _RATE_LOCK:
            _throttle_provider(provider, sleep_fn)
            try:
                resp = client.request(
                    method,
                    url,
                    params={k: str(v) for k, v in (params or {}).items()},
                    data=data,
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                if attempt < _MAX_RETRIES:
                    sleep_fn(min(1.0 * (attempt + 1), _MAX_RETRY_AFTER_SEC))
                    continue
                raise _error(
                    "ANALOG_EXTERNAL_NETWORK_ERROR",
                    f"External similarity request to '{provider}' failed: {exc}",
                    status_code=502,
                    details={"provider": provider, "url": url},
                ) from exc

        status_codes.append(resp.status_code)
        if resp.status_code in {429, 503, 504} and attempt < _MAX_RETRIES:
            retry_hdr = resp.headers.get("Retry-After")
            delay = 1.0 * (attempt + 1)
            if retry_hdr is not None:
                with suppress(ValueError):
                    delay = min(max(0.0, float(retry_hdr)), _MAX_RETRY_AFTER_SEC)
            sleep_fn(delay)
            continue
        return resp, status_codes

    raise _error(
        "ANALOG_EXTERNAL_NETWORK_ERROR",
        f"External similarity request to '{provider}' exhausted retries.",
        status_code=502,
        details={"provider": provider, "status_codes": status_codes},
    )


def _fetch_pubchem_candidates(
    *,
    client: httpx.Client,
    query_smiles: str,
    threshold_pct: int,
    max_candidates: int,
    sleep_fn: Callable[[float], None],
) -> tuple[list[_RawCandidate], bytes, list[int], str | None, bool, str, dict[str, object]]:
    params: dict[str, object] = {
        "Threshold": threshold_pct,
        "MaxRecords": max_candidates,
        "MaxSeconds": 15,
    }
    resp, codes = _send_bounded_request(
        client=client,
        provider="pubchem_pug_rest",
        method="POST",
        url=_PUBCHEM_ENDPOINT,
        params=params,
        data={"smiles": query_smiles},
        headers={"Accept": "application/json"},
        sleep_fn=sleep_fn,
    )
    raw = resp.content
    if len(raw) > MAX_ONLINE_RESPONSE_BYTES:
        raise _error(
            "ANALOG_EXTERNAL_RESPONSE_TOO_LARGE",
            "PubChem response exceeded the 10 MiB safety cap.",
            status_code=502,
            details={"bytes": len(raw), "max_bytes": MAX_ONLINE_RESPONSE_BYTES},
        )
    if resp.status_code == 404:
        # PubChem PUG-REST returns 404 PUGREST.NotFound when 0 neighbors meet Threshold.
        return [], raw or b"{}", codes, resp.headers.get("Date"), False, _PUBCHEM_ENDPOINT, params
    if resp.status_code != 200:
        raise _error(
            "ANALOG_EXTERNAL_PROVIDER_ERROR",
            f"PubChem PUG-REST returned HTTP {resp.status_code}.",
            status_code=502,
            details={"status_code": resp.status_code, "body_preview": resp.text[:300]},
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _error(
            "ANALOG_EXTERNAL_RESPONSE_INVALID",
            "PubChem PUG-REST returned unreadable JSON.",
            status_code=502,
        ) from exc

    props = (payload.get("PropertyTable") or {}).get("Properties") or []
    candidates: list[_RawCandidate] = []
    for row in props:
        if not isinstance(row, dict):
            continue
        cid = row.get("CID")
        smi = (
            row.get("SMILES")
            or row.get("IsomericSMILES")
            or row.get("CanonicalSMILES")
            or row.get("ConnectivitySMILES")
        )
        if not smi or cid is None:
            continue
        title = str(row.get("Title") or "").strip()
        cid_str = f"CID:{cid}"
        candidates.append(
            _RawCandidate(
                provider_compound_id=cid_str,
                identifier=title or cid_str,
                smiles=str(smi).strip(),
                provider_similarity=None,
            )
        )
    truncated_or_capped = len(props) >= max_candidates
    version_hdr = resp.headers.get("X-Throttling-Control") or resp.headers.get("Date")
    return candidates, raw, codes, version_hdr, truncated_or_capped, _PUBCHEM_ENDPOINT, params


def _fetch_chembl_candidates(
    *,
    client: httpx.Client,
    query_smiles: str,
    threshold_pct: int,
    max_candidates: int,
    sleep_fn: Callable[[float], None],
) -> tuple[list[_RawCandidate], bytes, list[int], str | None, bool, str, dict[str, object]]:
    encoded = urllib.parse.quote(query_smiles, safe="")
    url = f"{_CHEMBL_BASE}/{encoded}/{threshold_pct}.json"
    params: dict[str, object] = {"limit": min(max_candidates, MAX_ONLINE_CANDIDATES)}
    resp, codes = _send_bounded_request(
        client=client,
        provider="chembl_rest",
        method="GET",
        url=url,
        params=params,
        headers={"Accept": "application/json"},
        sleep_fn=sleep_fn,
    )
    raw = resp.content
    if len(raw) > MAX_ONLINE_RESPONSE_BYTES:
        raise _error(
            "ANALOG_EXTERNAL_RESPONSE_TOO_LARGE",
            "ChEMBL response exceeded the 10 MiB safety cap.",
            status_code=502,
            details={"bytes": len(raw), "max_bytes": MAX_ONLINE_RESPONSE_BYTES},
        )
    if resp.status_code != 200:
        raise _error(
            "ANALOG_EXTERNAL_PROVIDER_ERROR",
            f"ChEMBL REST returned HTTP {resp.status_code}.",
            status_code=502,
            details={"status_code": resp.status_code, "body_preview": resp.text[:300]},
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _error(
            "ANALOG_EXTERNAL_RESPONSE_INVALID",
            "ChEMBL REST returned unreadable JSON.",
            status_code=502,
        ) from exc

    molecules = payload.get("molecules") or []
    page_meta = payload.get("page_meta") or {}
    candidates: list[_RawCandidate] = []
    for row in molecules[:max_candidates]:
        if not isinstance(row, dict):
            continue
        chembl_id = str(row.get("molecule_chembl_id") or "").strip()
        structs = row.get("molecule_structures") or {}
        smi = str(structs.get("canonical_smiles") or "").strip()
        if not chembl_id or not smi:
            continue
        pref_name = str(row.get("pref_name") or "").strip()
        raw_sim = row.get("similarity")
        prov_sim: float | None = None
        if raw_sim is not None:
            try:
                val = float(raw_sim)
                prov_sim = round(val / 100.0 if val > 1.0 else val, 6)
                prov_sim = min(1.0, max(0.0, prov_sim))
            except ValueError:
                prov_sim = None
        candidates.append(
            _RawCandidate(
                provider_compound_id=chembl_id,
                identifier=pref_name or chembl_id,
                smiles=smi,
                provider_similarity=prov_sim,
            )
        )

    total_count = int(page_meta.get("total_count") or len(molecules))
    truncated_or_capped = (
        bool(page_meta.get("next"))
        or total_count > len(molecules)
        or len(molecules) >= max_candidates
    )
    version_hdr = resp.headers.get("X-ChEMBL-Release") or resp.headers.get("Date")
    return candidates, raw, codes, version_hdr, truncated_or_capped, url, params


def run_online_similarity_search(
    *,
    provider: Literal["pubchem_pug_rest", "chembl_rest"],
    query_smiles: str,
    seed_name: str,
    consent: ExternalTransmissionConsent,
    provider_min_similarity: float,
    min_local_rdkit_tanimoto: float,
    max_candidates: int,
    profile: AnalogFingerprintProfile,
    smarts_filter: str | None = None,
    transport: httpx.BaseTransport | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> OnlineSimilarityResult:
    """Run an explicit opt-in online similarity lookup behind cryptographic IP consent."""
    q_mol = Chem.MolFromSmiles(query_smiles)
    if q_mol is None:
        raise _error(
            "ANALOG_QUERY_SMILES_INVALID",
            "Seed chemical state SMILES could not be parsed by RDKit.",
        )
    q_iso, q_search, q_multi, q_undef = build_search_representation(q_mol, profile)

    # HARD IP / CONFIDENTIALITY GATE — verified BEFORE any HTTP client is instantiated!
    if not consent.verify_for(provider=provider, canonical_smiles=q_iso):
        raise _error(
            "ANALOG_EXTERNAL_CONSENT_REQUIRED",
            (
                "Explicit IP/confidentiality consent bound to the exact provider and canonical "
                "query SMILES is required before transmitting molecular structures off-machine."
            ),
            status_code=422,
            details={
                "provider": provider,
                "expected_query_canonical_smiles": q_iso,
            },
        )

    smarts_mol: Any | None = None
    if smarts_filter is not None:
        smarts_mol = Chem.MolFromSmarts(smarts_filter)
        if smarts_mol is None:
            raise _error(
                "ANALOG_SMARTS_INVALID",
                f"Substructure SMARTS pattern '{smarts_filter}' is invalid.",
                details={"smarts_filter": smarts_filter},
            )

    bounded_max = min(max(1, max_candidates), MAX_ONLINE_CANDIDATES)
    threshold_pct = min(100, max(40, int(round(provider_min_similarity * 100))))

    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
    with httpx.Client(timeout=timeout, transport=transport, follow_redirects=True) as client:
        if provider == "pubchem_pug_rest":
            (
                raw_candidates,
                raw_bytes,
                status_codes,
                provider_ver,
                capped,
                endpoint_url,
                req_params,
            ) = _fetch_pubchem_candidates(
                client=client,
                query_smiles=q_iso,
                threshold_pct=threshold_pct,
                max_candidates=bounded_max,
                sleep_fn=sleep_fn,
            )
            raw_filename = "pubchem_fastsimilarity_2d_response.json"
        else:
            (
                raw_candidates,
                raw_bytes,
                status_codes,
                provider_ver,
                capped,
                endpoint_url,
                req_params,
            ) = _fetch_chembl_candidates(
                client=client,
                query_smiles=q_iso,
                threshold_pct=threshold_pct,
                max_candidates=bounded_max,
                sleep_fn=sleep_fn,
            )
            raw_filename = "chembl_similarity_response.json"

    # Mandatory local RDKit Morgan ECFP4 recalculation on every downloaded candidate!
    gen = rdFingerprintGenerator.GetMorganGenerator(
        radius=profile.radius,
        fpSize=profile.fp_size,
        includeChirality=profile.include_chirality,
    )
    q_work = Chem.MolFromSmiles(q_search)
    q_fp = gen.GetFingerprint(q_work)
    rdkit_ver = rdkit_version_string()

    seed_hit = AnalogSearchHit(
        hit_id="seed-control",
        role=AnalogCandidateRole.SEED_CONTROL,
        identifier=seed_name,
        source_record_index=None,
        canonical_isomeric_smiles=q_iso,
        search_smiles=q_search,
        local_rdkit_tanimoto=1.0,
        provider_similarity=1.0,
        provider_compound_id=None,
        smarts_matched=(
            bool(q_mol.HasSubstructMatch(smarts_mol)) if smarts_mol is not None else None
        ),
        molecular_weight_g_mol=round(float(Descriptors.MolWt(q_mol)), 4),
        heavy_atom_count=int(q_mol.GetNumHeavyAtoms()),
        rotatable_bond_count=int(Lipinski.NumRotatableBonds(q_mol)),
        undefined_stereocenter_count=q_undef,
        had_multiple_fragments=q_multi,
        duplicate_of_hit_id=None,
    )

    invalid_skipped = 0
    matched: list[tuple[float, str, int, AnalogSearchHit]] = []
    seen_iso: set[str] = {q_iso}

    for idx, cand in enumerate(raw_candidates):
        mol = Chem.MolFromSmiles(cand.smiles)
        if mol is None or mol.GetNumHeavyAtoms() < 1:
            invalid_skipped += 1
            continue
        c_iso, c_search, c_multi, c_undef = build_search_representation(mol, profile)
        if c_iso in seen_iso:
            continue
        c_work = Chem.MolFromSmiles(c_search)
        if c_work is None:
            invalid_skipped += 1
            continue
        local_sim = min(
            1.0,
            max(0.0, float(DataStructs.TanimotoSimilarity(q_fp, gen.GetFingerprint(c_work)))),
        )
        if local_sim + 1e-12 < min_local_rdkit_tanimoto:
            continue
        smarts_ok: bool | None = None
        if smarts_mol is not None:
            smarts_ok = bool(mol.HasSubstructMatch(smarts_mol))
            if not smarts_ok:
                continue
        seen_iso.add(c_iso)
        hit = AnalogSearchHit(
            hit_id=f"{provider}-{idx}",
            role=AnalogCandidateRole.ANALOG,
            identifier=cand.identifier,
            source_record_index=idx,
            canonical_isomeric_smiles=c_iso,
            search_smiles=c_search,
            local_rdkit_tanimoto=round(local_sim, 6),
            provider_similarity=cand.provider_similarity,
            provider_compound_id=cand.provider_compound_id,
            smarts_matched=smarts_ok,
            molecular_weight_g_mol=round(float(Descriptors.MolWt(mol)), 4),
            heavy_atom_count=int(mol.GetNumHeavyAtoms()),
            rotatable_bond_count=int(Lipinski.NumRotatableBonds(mol)),
            undefined_stereocenter_count=c_undef,
            had_multiple_fragments=c_multi,
            duplicate_of_hit_id=None,
        )
        matched.append((local_sim, c_iso, idx, hit))

    matched.sort(key=lambda item: (-round(item[0], 12), item[1], item[2]))
    ordered_hits = [seed_hit, *(item[3] for item in matched)]

    warnings: list[StructuredWarning] = []
    if capped:
        warnings.append(
            StructuredWarning(
                code=WarningCode.ANALOG_EXTERNAL_PROVIDER_CAPPED,
                stage=_STAGE,
                message=(
                    f"Remote provider '{provider}' returned a capped/paginated subset "
                    f"(limit {bounded_max}); results are not guaranteed exhaustive across the "
                    "full external database (ADR-033 §5)."
                ),
                details={"provider": provider, "max_candidates": bounded_max},
            )
        )

    evidence = ExternalProviderEvidence(
        provider=provider,
        endpoint_url=endpoint_url,
        request_parameters=req_params,
        http_status_codes=status_codes,
        retrieved_at=datetime.now(UTC),
        provider_version=provider_ver,
        raw_response_filename=raw_filename,
        raw_response_sha256=sha256(raw_bytes).hexdigest(),
        raw_response_bytes=len(raw_bytes),
        truncated_or_capped=capped,
        consent=consent,
    )
    return OnlineSimilarityResult(
        query_canonical_isomeric_smiles=q_iso,
        query_search_smiles=q_search,
        rdkit_version=rdkit_ver,
        total_evaluated=len(raw_candidates),
        invalid_skipped=invalid_skipped,
        truncated_by_top_k=capped,
        hits=ordered_hits,
        external_evidence=evidence,
        raw_response_bytes=raw_bytes,
        warnings=warnings,
    )
