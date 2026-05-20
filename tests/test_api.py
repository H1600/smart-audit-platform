from io import BytesIO

from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_upload_run_query_export_csv_flow():
    payload = (
        "日期,凭证号,科目编码,科目名称,摘要,借方,贷方,余额\n"
        "2026-01-01,记-001,1002,银行存款,收到客户回款,1000,0,1000\n"
        "2026-01-01,记-001,1122,应收账款,冲减应收账款,0,1000,0\n"
    ).encode("utf-8-sig")
    upload = client.post(
        "/api/files/upload",
        files={"file": ("ledger.csv", BytesIO(payload), "text/csv")},
    )
    assert upload.status_code == 200
    task_id = upload.json()["task_id"]

    run = client.post(f"/api/tasks/{task_id}/run")
    assert run.status_code == 200

    task = client.get(f"/api/tasks/{task_id}").json()
    assert task["status"] == "completed"
    assert task["progress"] == 100

    records = client.get("/api/records", params={"voucher_no": "记-001"}).json()
    assert records["total"] >= 2

    report = client.get(f"/api/reports/{task_id}").json()
    assert report["reports"]

    exported = client.get(f"/api/export/{task_id}", params={"format": "xbrl"})
    assert exported.status_code == 200
    assert b"AuditLedger" in exported.content

