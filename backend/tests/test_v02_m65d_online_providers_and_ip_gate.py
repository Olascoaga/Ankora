"""Tests for M6.5d (Opt-in PubChem PUG-REST & ChEMBL REST connectors + cryptographic IP gate).

Uses deterministic httpx.MockTransport fixtures modeled directly on Gate 0 live probe payloads
so CI runs 100% offline with zero external flakiness.
"""

from __future__ import annotations

import json

import httpx
import pytest

from ankora_backend.adapters.external.analog_providers import run_online_similarity_search
from ankora_backend.domain.errors import AnkoraDomainError
from ankora_backend.schemas.analog_expansion import (
    AnalogCandidateRole,
    AnalogFingerprintProfile,
    ExternalTransmissionConsent,
    compute_external_consent_sha256,
)
from ankora_backend.schemas.warnings import WarningCode

_ASPIRIN = "CC(=O)Oc1ccccc1C(=O)O"


def test_online_search_blocks_before_any_http_call_without_valid_cryptographic_ip_consent() -> None:
    """ADR-033 §5: missing, unacknowledged, or mismatched consent fails 422 with 0 HTTP calls."""
    http_calls = 0

    def _forbid_http(request: httpx.Request) -> httpx.Response:
        nonlocal http_calls
        http_calls += 1
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(_forbid_http)
    profile = AnalogFingerprintProfile()

    # 1. acknowledge_external_transmission=False
    bad_consent_unack = ExternalTransmissionConsent(
        provider="pubchem_pug_rest",
        query_canonical_smiles=_ASPIRIN,
        consent_payload_sha256=compute_external_consent_sha256(
            provider="pubchem_pug_rest", query_canonical_smiles=_ASPIRIN
        ),
        acknowledge_external_transmission=False,
    )
    with pytest.raises(AnkoraDomainError) as exc1:
        run_online_similarity_search(
            provider="pubchem_pug_rest",
            query_smiles=_ASPIRIN,
            seed_name="aspirin",
            consent=bad_consent_unack,
            provider_min_similarity=0.8,
            min_local_rdkit_tanimoto=0.3,
            max_candidates=10,
            profile=profile,
            transport=transport,
            sleep_fn=lambda _: None,
        )
    assert exc1.value.code == "ANALOG_EXTERNAL_CONSENT_REQUIRED"
    assert http_calls == 0

    # 2. Wrong hash (bound to different molecule or provider)
    bad_consent_hash = ExternalTransmissionConsent(
        provider="pubchem_pug_rest",
        query_canonical_smiles=_ASPIRIN,
        consent_payload_sha256=compute_external_consent_sha256(
            provider="chembl_rest", query_canonical_smiles=_ASPIRIN
        ),
        acknowledge_external_transmission=True,
    )
    with pytest.raises(AnkoraDomainError) as exc2:
        run_online_similarity_search(
            provider="pubchem_pug_rest",
            query_smiles=_ASPIRIN,
            seed_name="aspirin",
            consent=bad_consent_hash,
            provider_min_similarity=0.8,
            min_local_rdkit_tanimoto=0.3,
            max_candidates=10,
            profile=profile,
            transport=transport,
            sleep_fn=lambda _: None,
        )
    assert exc2.value.code == "ANALOG_EXTERNAL_CONSENT_REQUIRED"
    assert http_calls == 0


def test_pubchem_pug_rest_archives_raw_response_retries_429_and_recalculates_local_rdkit() -> None:
    """ADR-033 §5: PubChem POST, Retry-After retry, raw SHA-256 archive, local RDKit score."""
    attempts = 0
    captured_posts: list[str] = []

    def _mock_pubchem(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        assert request.method == "POST"
        captured_posts.append(request.content.decode("utf-8"))
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, text="Busy")
        payload = {
            "PropertyTable": {
                "Properties": [
                    {
                        "CID": 2244,
                        "SMILES": "CC(=O)OC1=CC=CC=C1C(=O)O",
                        "Title": "Aspirin",
                    },
                    {
                        "CID": 4133,
                        "SMILES": "COC(=O)C1=CC=CC=C1O",
                        "Title": "Methyl Salicylate",
                    },
                    {
                        "CID": 5161,
                        "SMILES": "C1=CC=C(C(=C1)C(=O)OC2=CC=CC=C2C(=O)O)O",
                        "Title": "Salsalate",
                    },
                ]
            }
        }
        return httpx.Response(
            200,
            headers={"Date": "Sat, 21 Nov 2026 18:00:00 GMT"},
            content=json.dumps(payload).encode("utf-8"),
        )

    consent = ExternalTransmissionConsent(
        provider="pubchem_pug_rest",
        query_canonical_smiles=_ASPIRIN,
        consent_payload_sha256=compute_external_consent_sha256(
            provider="pubchem_pug_rest", query_canonical_smiles=_ASPIRIN
        ),
        acknowledge_external_transmission=True,
    )
    res = run_online_similarity_search(
        provider="pubchem_pug_rest",
        query_smiles=_ASPIRIN,
        seed_name="aspirin_seed",
        consent=consent,
        provider_min_similarity=0.9,
        min_local_rdkit_tanimoto=0.2,
        max_candidates=3,
        profile=AnalogFingerprintProfile(),
        transport=httpx.MockTransport(_mock_pubchem),
        sleep_fn=lambda _: None,
    )
    assert attempts == 2
    assert res.external_evidence.http_status_codes == [429, 200]
    assert res.external_evidence.raw_response_bytes > 50
    assert res.external_evidence.truncated_or_capped is True
    assert any(w.code is WarningCode.ANALOG_EXTERNAL_PROVIDER_CAPPED for w in res.warnings)
    assert res.hits[0].role is AnalogCandidateRole.SEED_CONTROL
    analogs = [h for h in res.hits if h.role is AnalogCandidateRole.ANALOG]
    # Aspirin (CID 2244) deduplicated against seed; Methyl Salicylate & Salsalate recalculated!
    assert {h.provider_compound_id for h in analogs} == {"CID:4133", "CID:5161"}
    for h in analogs:
        assert h.provider_similarity is None
        assert 0.2 <= h.local_rdkit_tanimoto < 1.0


def test_chembl_rest_keeps_provider_similarity_separate_from_local_rdkit_and_flags_salts() -> None:
    """ADR-033 §5: ChEMBL similarity stored separately from local RDKit; salts preserved."""

    def _mock_chembl(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "/80.json" in str(request.url)
        payload = {
            "page_meta": {"limit": 3, "next": "/chembl/next", "offset": 0, "total_count": 12},
            "molecules": [
                {
                    "molecule_chembl_id": "CHEMBL2296002",
                    "pref_name": None,
                    "similarity": "100",
                    "molecule_structures": {
                        "canonical_smiles": "CC(=O)Oc1ccc(F)cc1C(=O)O.[Na+]"
                    },
                },
                {
                    "molecule_chembl_id": "CHEMBL25",
                    "pref_name": "ASPIRIN",
                    "similarity": "100",
                    "molecule_structures": {"canonical_smiles": "CC(=O)Oc1ccccc1C(=O)O"},
                },
                {
                    "molecule_chembl_id": "CHEMBL1201189",
                    "pref_name": "METHYL SALICYLATE",
                    "similarity": "82",
                    "molecule_structures": {"canonical_smiles": "COC(=O)c1ccccc1O"},
                },
            ],
        }
        return httpx.Response(
            200,
            headers={"X-ChEMBL-Release": "ChEMBL_35"},
            content=json.dumps(payload).encode("utf-8"),
        )

    consent = ExternalTransmissionConsent(
        provider="chembl_rest",
        query_canonical_smiles=_ASPIRIN,
        consent_payload_sha256=compute_external_consent_sha256(
            provider="chembl_rest", query_canonical_smiles=_ASPIRIN
        ),
        acknowledge_external_transmission=True,
    )
    res = run_online_similarity_search(
        provider="chembl_rest",
        query_smiles=_ASPIRIN,
        seed_name="aspirin_seed",
        consent=consent,
        provider_min_similarity=0.8,
        min_local_rdkit_tanimoto=0.2,
        max_candidates=3,
        profile=AnalogFingerprintProfile(),
        transport=httpx.MockTransport(_mock_chembl),
        sleep_fn=lambda _: None,
    )
    assert res.external_evidence.provider_version == "ChEMBL_35"
    assert res.external_evidence.truncated_or_capped is True
    analogs = [h for h in res.hits if h.role is AnalogCandidateRole.ANALOG]
    by_id = {h.provider_compound_id: h for h in analogs}
    assert "CHEMBL25" not in by_id  # identical to seed
    assert "CHEMBL2296002" in by_id  # salt preserved as distinct multi-fragment record!
    assert by_id["CHEMBL2296002"].had_multiple_fragments is True
    assert by_id["CHEMBL2296002"].provider_similarity == pytest.approx(1.0)
    assert by_id["CHEMBL1201189"].provider_similarity == pytest.approx(0.82)
    assert by_id["CHEMBL1201189"].local_rdkit_tanimoto != by_id["CHEMBL1201189"].provider_similarity
