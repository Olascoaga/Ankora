from fastapi.testclient import TestClient

from ankora_backend.api.app import create_app
from ankora_backend.schemas.work_recovery import WorkKind, WorkRetryResponse


def test_health_endpoint() -> None:
    response = TestClient(create_app()).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "backend_version": "0.1.0"}


def test_work_recovery_endpoint_reports_startup_reconciliation(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))

    response = TestClient(create_app()).get("/api/v1/work/recovery")

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_work_retry_endpoint_is_typed_and_requires_explicit_confirmation(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ANKORA_DATA_DIR", str(tmp_path))
    app = create_app()
    interrupted_id = "00000000-0000-0000-0000-000000000001"

    response = TestClient(app).post(
        f"/api/v1/work/recovery/{WorkKind.VINA_JOB.value}/{interrupted_id}/retry",
        json={"acknowledge_new_immutable_attempt": False},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "WORK_RETRY_CONFIRMATION_REQUIRED"
    specification = TestClient(app).get("/api/openapi.json").json()
    operation = specification["paths"][
        "/api/v1/work/recovery/{work_kind}/{work_id}/retry"
    ]["post"]
    assert operation["responses"]["201"]["content"]["application/json"]["schema"] == {
        "$ref": f"#/components/schemas/{WorkRetryResponse.__name__}"
    }


def test_system_endpoint_reports_runtime() -> None:
    response = TestClient(create_app()).get("/api/v1/system")
    body = response.json()

    assert response.status_code == 200
    assert body["platform"] == "windows"
    assert body["architecture"] in {"x86_64", "arm64"}
    assert body["python_version"].startswith("3.12")
    assert body["python_environment"]
    assert body["app_mode"] == "development"


def test_tools_endpoint_has_stable_contract(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("ANKORA_VINA_PATH", raising=False)
    monkeypatch.delenv("ANKORA_GNINA_PATH", raising=False)
    monkeypatch.delenv("ANKORA_AUTOGRID4_PATH", raising=False)
    monkeypatch.delenv("ANKORA_AUTODOCK4_PATH", raising=False)
    monkeypatch.delenv("ANKORA_AUTODOCK_GPU_PATH", raising=False)

    response = TestClient(create_app()).get("/api/v1/tools")

    assert response.status_code == 200
    assert set(response.json()) == {
        "vina",
        "gnina",
        "autogrid4",
        "autodock4",
        "autodock_gpu",
        "pdbfixer",
        "pdb2pqr",
        "propka",
        "meeko",
        "meeko_ligand",
        "p2rank",
    }
    for status in response.json().values():
        assert set(status) == {"available", "path", "version", "architecture", "sha256"}


def test_windows_tauri_origin_is_allowed() -> None:
    response = TestClient(create_app()).get(
        "/api/v1/health",
        headers={"Origin": "http://tauri.localhost"},
    )

    assert response.headers["access-control-allow-origin"] == "http://tauri.localhost"


def test_upload_endpoint_rejects_request_with_no_origin() -> None:
    """multipart/form-data is a CORS-safelisted content type, so a browser
    sends this as a "simple request" with no preflight — CORS headers alone
    only stop a malicious page's script from reading the response, not from
    triggering the upload's side effects. Requiring a known Origin closes
    that gap; this reproduces exactly what a cross-origin page's fetch()
    would send (no Origin header at all is also what TestClient sends by
    default, matching a non-browser HTTP client with no CORS enforcement)."""
    response = TestClient(create_app()).post(
        "/api/v1/structures/import",
        files={"file": ("evil.pdb", b"not a real structure", "chemical/x-pdb")},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "UPLOAD_ORIGIN_NOT_ALLOWED"


def test_upload_endpoint_rejects_untrusted_origin() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/ligands/import",
        headers={"Origin": "http://malicious.example"},
        files={"file": ("evil.sdf", b"not a real ligand", "chemical/x-mdl-sdfile")},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "UPLOAD_ORIGIN_NOT_ALLOWED"


def test_pose_complex_export_rejects_untrusted_origin_before_writing() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/results/campaigns/vina_job/job-1/compounds/ligand-1/poses/pose-1/complex/export",
        headers={"Origin": "http://malicious.example"},
        json={"molecule_name": "synthetic ligand", "destination": "outside"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "UPLOAD_ORIGIN_NOT_ALLOWED"


def test_pose_complex_export_is_a_typed_write_endpoint() -> None:
    specification = TestClient(create_app()).get("/api/openapi.json").json()
    path = (
        "/api/v1/results/campaigns/{engine}/{record_id}/compounds/{ligand_id}/poses/"
        "{pose_artifact_id}/complex/export"
    )

    assert "post" in specification["paths"][path]
    assert specification["paths"][path]["post"]["responses"]["201"]


def test_upload_endpoint_allows_the_real_desktop_origin() -> None:
    response = TestClient(create_app()).post(
        "/api/v1/structures/import",
        headers={"Origin": "tauri://localhost"},
        files={"file": ("real.pdb", b"not a real structure either", "chemical/x-pdb")},
    )

    # The middleware must not be what blocks this request — whatever status
    # code the route itself returns for unparseable content is fine, as
    # long as it isn't the origin check.
    assert response.status_code != 403 or response.json().get("code") != "UPLOAD_ORIGIN_NOT_ALLOWED"
