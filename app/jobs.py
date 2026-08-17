import logging
import threading
from datetime import UTC, datetime

from .config import settings
from .db import all_rows, jsonb, one, pool
from .esg_export import build_report_artifact
from .privacy import purge_personal_data, purge_sessions


logger = logging.getLogger(__name__)

# 실패한 잡을 몇 번까지 다시 집을지. 워커는 PENDING만 집으므로, 한도 안이면 PENDING으로
# 되돌리고 넘으면 FAILED로 굳힌다. 무한 재시도는 깨진 잡이 워커를 계속 돌게 만든다.
MAX_ATTEMPTS = 3


REPORT_METRICS_SQL = """SELECT m.id AS "metricId",m.name,m.category,v.id AS "metricVersionId",v.version_no AS "versionNo",
          v.formula,v.unit,v.target,sum(em.value)::float8 AS value,count(em.id)::int AS "measurementCount",
          coalesce(sum((SELECT count(*) FROM esg_evidence e WHERE e.measurement_id=em.id)),0)::int AS "evidenceCount",
          max(em.measured_at) AS "lastMeasuredAt"
   FROM esg_measurements em JOIN esg_metric_versions v ON v.id=em.metric_version_id
   JOIN esg_metrics m ON m.id=v.metric_id
   WHERE em.festival_id=%s AND em.status='APPROVED' AND em.measured_at BETWEEN %s AND %s
   GROUP BY m.id,m.name,m.category,v.id,v.version_no,v.formula,v.unit,v.target ORDER BY m.category,m.name"""


def _comparison(connection, report: dict) -> list[dict]:
    """비교 대상 축제의 같은 지표 실적.

    compareWithFestivalId는 받아서 저장만 하고 스냅샷에 반영되지 않아, 화면에 비교를 그릴
    방법이 없었다. 지표 이름이 같은 것끼리 짝지어 값 차이를 계산한다(축제마다 지표 행이
    따로 있어 id로는 이어지지 않는다).
    """
    if not report.get("compare_with_festival_id"):
        return []
    other = all_rows(connection, REPORT_METRICS_SQL,
                     (report["compare_with_festival_id"], report["period_from"], report["period_to"]))
    return [{"name": row["name"], "category": row["category"], "unit": row["unit"], "value": row["value"]}
            for row in other]


def _generate_esg_report(connection, job: dict) -> dict:
    report = one(connection, "SELECT * FROM esg_reports WHERE id=%s", (job["resource_id"],))
    if not report:
        raise ValueError("report not found")
    metrics = all_rows(connection, REPORT_METRICS_SQL,
                       (report["festival_id"], report["period_from"], report["period_to"]))
    comparison = _comparison(connection, report)
    baseline = {row["name"]: row["value"] for row in comparison}
    for metric in metrics:
        if metric["name"] in baseline:
            metric["comparisonValue"] = baseline[metric["name"]]
            metric["comparisonDelta"] = round((metric["value"] or 0) - (baseline[metric["name"]] or 0), 4)
    snapshot = {"generatedAt": datetime.now(UTC).isoformat(), "metrics": metrics,
                "comparison": {"festivalId": str(report["compare_with_festival_id"]), "metrics": comparison}
                if comparison else None}
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
    return {"reportId": str(job["resource_id"]), "format": export_format, "artifacts": [artifact]}


# job_type -> (handler, 실패 시 esg_reports.status를 되돌릴지) — GENERATE는 보고서가 아직 DRAFT조차
# 안 된 상태라 FAILED로 굳혀야 하지만, EXPORT는 이미 APPROVED까지 간 보고서라 실패해도 그대로 두고
# 재시도(다시 exports 호출)할 수 있게 둔다.
JOB_HANDLERS = {
    "GENERATE_ESG_REPORT": (_generate_esg_report, True),
    "EXPORT_ESG_REPORT": (_export_esg_report, False),
}


def fail_job(connection, job: dict, handler_known: bool, revert_resource: bool, error: Exception) -> None:
    """실패 처리.

    한도 안이면 PENDING으로 되돌려 다음 순회에서 다시 집게 한다. 알 수 없는 job_type은
    다시 시도해도 결과가 같으므로 곧바로 FAILED로 굳힌다.
    """
    attempts = job["attempts"] + 1
    retryable = handler_known and attempts < MAX_ATTEMPTS
    connection.execute("UPDATE jobs SET status=%s,attempts=%s,error=%s,updated_at=now() WHERE id=%s",
                       ("PENDING" if retryable else "FAILED", attempts, str(error), job["id"]))
    logger.warning("잡 실패 %s (%s) 시도 %s/%s: %s", job["id"], job["job_type"], attempts, MAX_ATTEMPTS, error)
    if not retryable and job["resource_type"] == "ESG_REPORT" and revert_resource:
        connection.execute("UPDATE esg_reports SET status='FAILED',updated_at=now() WHERE id=%s", (job["resource_id"],))


def process_one_job() -> bool:
    with pool.connection() as connection:
        job = one(connection, """SELECT * FROM jobs WHERE status='PENDING' AND attempts<%s
            ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1""", (MAX_ATTEMPTS,))
        if not job:
            return False
        connection.execute("UPDATE jobs SET status='RUNNING',updated_at=now() WHERE id=%s", (job["id"],))
        handler_entry = JOB_HANDLERS.get(job["job_type"])
        try:
            # 핸들러를 세이브포인트 안에서 돌린다. DB 오류(잘못된 SQL 등)는 트랜잭션을
            # abort 상태로 만들어서, 세이브포인트가 없으면 아래 fail_job의 UPDATE까지 실패한다.
            # 그러면 attempts가 오르지 않은 채 전부 롤백돼 워커가 같은 잡을 영원히 다시 집는다.
            with connection.transaction():
                if not handler_entry:
                    raise ValueError(f"unsupported job type: {job['job_type']}")
                handler, _ = handler_entry
                result = handler(connection, job)
            connection.execute("UPDATE jobs SET status='COMPLETED',result=%s,updated_at=now() WHERE id=%s", (jsonb(result), job["id"]))
        except Exception as error:  # job failure belongs in durable state
            fail_job(connection, job, handler_entry is not None, bool(handler_entry and handler_entry[1]), error)
        return True


def purge_expired() -> None:
    """만료·폐기 데이터 정리와 OPS-11 개인정보 파기.

    운영 부산물(멱등성 레코드·리프레시 토큰)은 여기서 지우고, 개인정보 항목은 보유기간
    정책표를 단일 기준으로 쓰는 privacy.purge_personal_data가 참조 데이터까지 연쇄로
    지운다. 파기 결과는 감사 로그(OPS-09)에 남는다.

    끝나지 않은 축제의 세션은 정책표 대상이 아니므로, 만료된 지 오래된 세션은 기존
    보존 기간으로 함께 정리한다(축제가 ENDED로 넘어가지 않은 채 방치되는 경우 대비).
    """
    with pool.connection() as connection:
        connection.execute("DELETE FROM idempotency_records WHERE created_at<now()-make_interval(days => %s)",
                           (settings.idempotency_retention_days,))
        connection.execute("DELETE FROM refresh_tokens WHERE expires_at<now()-interval '30 days' OR revoked_at<now()-interval '30 days'")
        counts = purge_personal_data(connection)
        stale = purge_sessions(connection, "expires_at<now()-make_interval(days => %s)",
                               (settings.visitor_session_retention_days,))
        logger.info("개인정보 파기: %s, 만료 세션 %s건", counts, stale)


# 정리는 매 순회마다 돌릴 필요가 없다. 워커가 1초마다 깨어나므로 1시간에 한 번꼴.
PURGE_EVERY_TICKS = 3600


def start_worker() -> tuple[threading.Event, threading.Thread]:
    stopped = threading.Event()

    def run() -> None:
        ticks = 0
        while not stopped.wait(1):
            ticks += 1
            try:
                while process_one_job():
                    pass
                if ticks % PURGE_EVERY_TICKS == 0:
                    purge_expired()
            except Exception:
                # print는 구조화된 로그·경보에 잡히지 않는다. 스택까지 남겨야 원인을 본다.
                logger.exception("잡 워커 순회 실패")

    thread = threading.Thread(target=run, name="festival-jobs", daemon=True)
    thread.start()
    return stopped, thread
