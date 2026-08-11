import threading
from datetime import UTC, datetime

from .db import all_rows, jsonb, one, pool


def process_one_job() -> bool:
    with pool.connection() as connection:
        job = one(connection, "SELECT * FROM jobs WHERE status='PENDING' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1")
        if not job:
            return False
        connection.execute("UPDATE jobs SET status='RUNNING',updated_at=now() WHERE id=%s", (job["id"],))
        try:
            if job["job_type"] != "GENERATE_ESG_REPORT":
                raise ValueError(f"unsupported job type: {job['job_type']}")
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
            connection.execute("UPDATE jobs SET status='COMPLETED',result=%s,updated_at=now() WHERE id=%s", (jsonb({"reportId": str(job["resource_id"])}), job["id"]))
        except Exception as error:  # job failure belongs in durable state
            connection.execute("UPDATE jobs SET status='FAILED',error=%s,updated_at=now() WHERE id=%s", (str(error), job["id"]))
            if job["resource_type"] == "ESG_REPORT":
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
