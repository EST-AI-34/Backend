import threading
from datetime import UTC, datetime

from .db import all_rows, jsonb, one, pool
from .esg_export import build_report_artifact


def _generate_esg_report(connection, job: dict) -> dict:
    report = one(connection, "SELECT * FROM esg_reports WHERE id=%s", (job["resource_id"],))
    if not report:
        raise ValueError("report not found")
    metrics = all_rows(
        connection,
        """SELECT m.id AS "metricId",m.name,m.category,v.id AS "metricVersionId",v.version_no AS "versionNo",
                  v.formula,v.unit,v.target,sum(em.value)::float8 AS value,count(em.id)::int AS "measurementCount",
                  coalesce(sum((SELECT count(*) FROM esg_evidence e WHERE e.measurement_id=em.id)),0)::int AS "evidenceCount",
                  max(em.measured_at) AS "lastMeasuredAt"
           FROM esg_measurements em JOIN esg_metric_versions v ON v.id=em.metric_version_id
           JOIN esg_metrics m ON m.id=v.metric_id
           WHERE em.festival_id=%s AND em.status='APPROVED' AND em.measured_at BETWEEN %s AND %s
           GROUP BY m.id,m.name,m.category,v.id,v.version_no,v.formula,v.unit,v.target ORDER BY m.category,m.name""",
        (report["festival_id"], report["period_from"], report["period_to"]),
    )
    snapshot = {"generatedAt": datetime.now(UTC).isoformat(), "metrics": metrics}
    connection.execute("UPDATE esg_reports SET status='DRAFT',snapshot=%s,updated_at=now() WHERE id=%s", (jsonb(snapshot), job["resource_id"]))
    return {"reportId": str(job["resource_id"])}


def _export_esg_report(connection, job: dict) -> dict:
    report = one(connection, "SELECT * FROM esg_reports WHERE id=%s", (job["resource_id"],))
    if not report:
        raise ValueError("report not found")
    if report["status"] != "APPROVED":
        raise ValueError("report is not in APPROVED status")
    # export_report(admin_esg.py)가 요청 시점 format을 여기에 임시로 넣어둔다(job에 별도 입력 컬럼이 없다).
    export_format = (job.get("result") or {}).get("format") or report["format"]
    artifact = build_report_artifact(report, export_format)
    connection.execute("UPDATE esg_reports SET status='EXPORTED',updated_at=now() WHERE id=%s", (job["resource_id"],))
    return {"reportId": str(job["resource_id"]), "artifacts": [artifact]}


# job_type -> (handler, 실패 시 esg_reports.status를 되돌릴지) — GENERATE는 보고서가 아직 DRAFT조차
# 안 된 상태라 FAILED로 굳혀야 하지만, EXPORT는 이미 APPROVED까지 간 보고서라 실패해도 그대로 두고
# 재시도(다시 exports 호출)할 수 있게 둔다.
JOB_HANDLERS = {
    "GENERATE_ESG_REPORT": (_generate_esg_report, True),
    "EXPORT_ESG_REPORT": (_export_esg_report, False),
}


def process_one_job() -> bool:
    with pool.connection() as connection:
        job = one(connection, "SELECT * FROM jobs WHERE status='PENDING' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1")
        if not job:
            return False
        connection.execute("UPDATE jobs SET status='RUNNING',updated_at=now() WHERE id=%s", (job["id"],))
        handler_entry = JOB_HANDLERS.get(job["job_type"])
        try:
            if not handler_entry:
                raise ValueError(f"unsupported job type: {job['job_type']}")
            handler, revert_resource_on_failure = handler_entry
            result = handler(connection, job)
            connection.execute("UPDATE jobs SET status='COMPLETED',result=%s,updated_at=now() WHERE id=%s", (jsonb(result), job["id"]))
        except Exception as error:  # job failure belongs in durable state
            connection.execute("UPDATE jobs SET status='FAILED',error=%s,updated_at=now() WHERE id=%s", (str(error), job["id"]))
            if job["resource_type"] == "ESG_REPORT" and handler_entry and handler_entry[1]:
                connection.execute("UPDATE esg_reports SET status='FAILED',updated_at=now() WHERE id=%s", (job["resource_id"],))
        return True


def start_worker() -> tuple[threading.Event, threading.Thread]:
    stopped = threading.Event()

    def run() -> None:
        while not stopped.wait(1):
            try:
                while process_one_job():
                    pass
            except Exception as error:
                print(f"job worker: {error}")

    thread = threading.Thread(target=run, name="festival-jobs", daemon=True)
    thread.start()
    return stopped, thread
