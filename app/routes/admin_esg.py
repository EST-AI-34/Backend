from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response
from psycopg import Connection
from psycopg.errors import UniqueViolation

from ..db import all_rows, audit, database, idempotent, jsonb, one
from ..domain import validate_measurement_review
from ..errors import bad_request, conflict, not_found
from ..http import idempotent_success, success
from ..schemas import (EsgReportIn, EvidenceIn, ExportIn, MeasurementIn, MeasurementPatch, MetricIn,
                       MetricVersionIn, ReportPatch, ReviewIn)
from ..security import festival_access, roles


router=APIRouter()


@router.get("/admin/festivals/{festival_id}/esg/dashboard")
def esg_dashboard(festival_id:str,request:Request,_:Annotated[dict,Depends(festival_access)],connection:Annotated[Connection,Depends(database)],category:str|None=None):
    rows=all_rows(connection,"""WITH latest AS (
        SELECT DISTINCT ON (metric_id) * FROM esg_metric_versions ORDER BY metric_id,version_no DESC
      ) SELECT m.id,m.name,m.category,v.id AS metric_version_id,v.version_no,v.formula,v.unit,v.target,
        coalesce(sum(em.value) FILTER(WHERE em.status='APPROVED'),0) AS approved_value,
        count(em.*) FILTER(WHERE em.status IN('DRAFT','IN_REVIEW','REJECTED'))::int AS unapproved_count,
        count(em.*) FILTER(WHERE em.status='APPROVED')::int AS approved_count,
        CASE WHEN v.target IS NULL OR v.target=0 THEN NULL
          ELSE round(coalesce(sum(em.value) FILTER(WHERE em.status='APPROVED'),0)/v.target*100,2) END AS achievement_rate,
        max(em.measured_at) FILTER(WHERE em.status='APPROVED') AS latest_measurement_at
      FROM esg_metrics m LEFT JOIN latest v ON v.metric_id=m.id LEFT JOIN esg_measurements em ON em.metric_version_id=v.id
      WHERE m.festival_id=%s AND m.status='ACTIVE' AND (%s::text IS NULL OR m.category=%s)
      GROUP BY m.id,v.id,v.version_no,v.formula,v.unit,v.target ORDER BY m.category,m.name""",(festival_id,category,category))
    warnings=[{"metricId":row["id"],"type":"MISSING_DATA" if row["approved_count"]==0 else "UNAPPROVED_DATA","count":row["unapproved_count"]}
        for row in rows if row["approved_count"]==0 or row["unapproved_count"]>0]
    return success(request,{"metrics":rows,"dataQualityWarnings":warnings,"source":"APPROVED_MEASUREMENTS_ONLY"})


@router.get("/admin/festivals/{festival_id}/esg/metrics")
def metrics(festival_id:str,request:Request,_:Annotated[dict,Depends(festival_access)],connection:Annotated[Connection,Depends(database)]):
    rows=all_rows(connection,"""SELECT m.*,coalesce(jsonb_agg(to_jsonb(v) ORDER BY v.version_no DESC)
        FILTER(WHERE v.id IS NOT NULL),'[]') versions FROM esg_metrics m LEFT JOIN esg_metric_versions v ON v.metric_id=m.id
        WHERE m.festival_id=%s GROUP BY m.id ORDER BY m.created_at""",(festival_id,));return success(request,rows)


@router.post("/admin/festivals/{festival_id}/esg/metrics",status_code=201)
def create_metric(festival_id:str,body:MetricIn,request:Request,_:Annotated[dict,Depends(festival_access)],user:Annotated[dict,Depends(roles("SUPER_ADMIN","FESTIVAL_MANAGER"))],connection:Annotated[Connection,Depends(database)]):
    row=one(connection,"INSERT INTO esg_metrics(festival_id,name,category,created_by) VALUES(%s,%s,%s,%s) RETURNING *",(festival_id,body.name,body.category,user["id"]));return success(request,row)


@router.get("/admin/festivals/{festival_id}/esg/metrics/{metric_id}")
def metric(festival_id:str,metric_id:str,request:Request,_:Annotated[dict,Depends(festival_access)],connection:Annotated[Connection,Depends(database)]):
    row=one(connection,"SELECT * FROM esg_metrics WHERE id=%s AND festival_id=%s",(metric_id,festival_id))
    if not row:raise not_found()
    row["versions"]=all_rows(connection,"SELECT * FROM esg_metric_versions WHERE metric_id=%s ORDER BY version_no DESC",(metric_id,));return success(request,row)


@router.post("/admin/festivals/{festival_id}/esg/metrics/{metric_id}/versions",status_code=201)
def create_metric_version(festival_id:str,metric_id:str,body:MetricVersionIn,request:Request,_:Annotated[dict,Depends(festival_access)],user:Annotated[dict,Depends(roles("SUPER_ADMIN","FESTIVAL_MANAGER"))],connection:Annotated[Connection,Depends(database)]):
    if not one(connection,"SELECT 1 FROM esg_metrics WHERE id=%s AND festival_id=%s",(metric_id,festival_id)):raise not_found()
    row=one(connection,"""INSERT INTO esg_metric_versions(metric_id,version_no,formula,unit,target,source_requirements,evidence_required,created_by)
        SELECT %s,coalesce(max(version_no),0)+1,%s,%s,%s,%s,%s,%s FROM esg_metric_versions WHERE metric_id=%s RETURNING *""",(metric_id,body.formula,body.unit,body.target,jsonb(body.source_requirements),body.evidence_required,user["id"],metric_id));return success(request,row)


@router.get("/admin/festivals/{festival_id}/esg/measurements")
def measurements(festival_id:str,request:Request,_:Annotated[dict,Depends(festival_access)],connection:Annotated[Connection,Depends(database)],status:str|None=None):
    rows=all_rows(connection,"""SELECT em.*,m.name AS metric_name,m.category,v.version_no,v.unit,
        (SELECT count(*) FROM esg_evidence e WHERE e.measurement_id=em.id)::int AS evidence_count
        FROM esg_measurements em JOIN esg_metric_versions v ON v.id=em.metric_version_id JOIN esg_metrics m ON m.id=v.metric_id
        WHERE em.festival_id=%s AND (%s::text IS NULL OR em.status=%s) ORDER BY em.measured_at DESC""",(festival_id,status,status));return success(request,rows)


@router.post("/admin/festivals/{festival_id}/esg/measurements",status_code=201)
def create_measurement(festival_id:str,body:MeasurementIn,request:Request,response:Response,_:Annotated[dict,Depends(festival_access)],user:Annotated[dict,Depends(roles("SUPER_ADMIN","FESTIVAL_MANAGER","FIELD_OPERATOR"))],connection:Annotated[Connection,Depends(database)],idempotency_key:Annotated[str|None,Header(alias="Idempotency-Key")]=None):
    def work():
        if not one(connection,"""SELECT 1 FROM esg_metric_versions v JOIN esg_metrics m ON m.id=v.metric_id
            WHERE v.id=%s AND m.festival_id=%s""",(body.metric_version_id,festival_id)):raise bad_request("FESTIVAL_SCOPE_MISMATCH","지표 버전이 같은 축제에 속하지 않습니다.")
        try:
            row=one(connection,"""INSERT INTO esg_measurements(festival_id,metric_version_id,value,source_type,source_ref,dedupe_key,
                measured_at,supersedes_id,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",(festival_id,body.metric_version_id,body.value,body.source_type,body.source_ref,body.dedupe_key,body.measured_at,body.supersedes_id,user["id"]))
        except UniqueViolation as error:raise conflict("DUPLICATE_MEASUREMENT","같은 지표 버전과 중복 키의 실적이 이미 존재합니다.") from error
        audit(connection,festival_id=festival_id,actor_id=str(user["id"]),action="CREATE",resource_type="ESG_MEASUREMENT",resource_id=str(row["id"]),after_data=row,request_id=request.state.request_id);return 201,row
    return idempotent_success(request,response,idempotent(connection,key=idempotency_key,scope=f"esg-measurement:{festival_id}",body=body.model_dump(),work=work))


@router.get("/admin/festivals/{festival_id}/esg/measurements/{measurement_id}")
def measurement(festival_id:str,measurement_id:str,request:Request,_:Annotated[dict,Depends(festival_access)],connection:Annotated[Connection,Depends(database)]):
    row=one(connection,"""SELECT em.*,to_jsonb(v) metric_version FROM esg_measurements em JOIN esg_metric_versions v ON v.id=em.metric_version_id
        WHERE em.id=%s AND em.festival_id=%s""",(measurement_id,festival_id))
    if not row:raise not_found()
    row["evidence"]=all_rows(connection,"SELECT * FROM esg_evidence WHERE measurement_id=%s ORDER BY created_at",(measurement_id,));row["reviews"]=all_rows(connection,"SELECT * FROM esg_reviews WHERE measurement_id=%s ORDER BY created_at",(measurement_id,));return success(request,row)


@router.patch("/admin/festivals/{festival_id}/esg/measurements/{measurement_id}")
def patch_measurement(festival_id:str,measurement_id:str,body:MeasurementPatch,request:Request,_:Annotated[dict,Depends(festival_access)],user:Annotated[dict,Depends(roles("SUPER_ADMIN","FESTIVAL_MANAGER","FIELD_OPERATOR"))],connection:Annotated[Connection,Depends(database)]):
    row=one(connection,"""UPDATE esg_measurements SET value=coalesce(%s,value),source_type=coalesce(%s,source_type),
        source_ref=coalesce(%s,source_ref),measured_at=coalesce(%s,measured_at),updated_at=now()
        WHERE id=%s AND festival_id=%s AND status IN('DRAFT','REJECTED') RETURNING *""",(body.value,body.source_type,body.source_ref,body.measured_at,measurement_id,festival_id))
    if not row:raise bad_request("IMMUTABLE_APPROVED_MEASUREMENT","승인 전 실적만 수정할 수 있습니다.")
    return success(request,row)


@router.post("/admin/festivals/{festival_id}/esg/measurements/{measurement_id}/evidence",status_code=201)
def add_evidence(festival_id:str,measurement_id:str,body:EvidenceIn,request:Request,_:Annotated[dict,Depends(festival_access)],user:Annotated[dict,Depends(roles("SUPER_ADMIN","FESTIVAL_MANAGER","FIELD_OPERATOR"))],connection:Annotated[Connection,Depends(database)]):
    if not one(connection,"SELECT 1 FROM esg_measurements WHERE id=%s AND festival_id=%s AND status NOT IN('APPROVED','SUPERSEDED')",(measurement_id,festival_id)):raise bad_request("IMMUTABLE_APPROVED_MEASUREMENT","승인 전 실적에만 증빙을 추가할 수 있습니다.")
    row=one(connection,"INSERT INTO esg_evidence(measurement_id,file_id,file_hash,evidence_type,issued_at) VALUES(%s,%s,%s,%s,%s) RETURNING *",(measurement_id,body.file_id,body.file_hash,body.evidence_type,body.issued_at));return success(request,row)


@router.post("/admin/festivals/{festival_id}/esg/measurements/{measurement_id}/reviews")
def review_measurement(festival_id:str,measurement_id:str,body:ReviewIn,request:Request,_:Annotated[dict,Depends(festival_access)],user:Annotated[dict,Depends(roles("SUPER_ADMIN","REVIEWER"))],connection:Annotated[Connection,Depends(database)]):
    row=one(connection,"""SELECT em.*,v.formula,v.unit,v.source_requirements,v.evidence_required,
        (SELECT count(*) FROM esg_evidence e WHERE e.measurement_id=em.id)::int evidence_count
        FROM esg_measurements em JOIN esg_metric_versions v ON v.id=em.metric_version_id WHERE em.id=%s AND em.festival_id=%s""",(measurement_id,festival_id))
    if not row:raise not_found()
    validate_measurement_review(row,row["evidence_count"],body.decision)
    connection.execute("INSERT INTO esg_reviews(measurement_id,reviewer_id,decision,comment) VALUES(%s,%s,%s,%s)",(measurement_id,user["id"],body.decision,body.comment))
    updated=one(connection,"UPDATE esg_measurements SET status=%s,updated_at=now() WHERE id=%s RETURNING *",(body.decision,measurement_id))
    if body.decision=="APPROVED" and updated["supersedes_id"]:connection.execute("UPDATE esg_measurements SET status='SUPERSEDED',updated_at=now() WHERE id=%s AND status='APPROVED'",(updated["supersedes_id"],))
    audit(connection,festival_id=festival_id,actor_id=str(user["id"]),action=body.decision,resource_type="ESG_MEASUREMENT",resource_id=measurement_id,after_data=updated,request_id=request.state.request_id);return success(request,updated)


@router.get("/admin/festivals/{festival_id}/esg/reports")
def reports(festival_id:str,request:Request,_:Annotated[dict,Depends(festival_access)],connection:Annotated[Connection,Depends(database)]):return success(request,all_rows(connection,"SELECT * FROM esg_reports WHERE festival_id=%s ORDER BY created_at DESC",(festival_id,)))


@router.post("/admin/festivals/{festival_id}/esg/reports",status_code=202)
def create_report(festival_id:str,body:EsgReportIn,request:Request,response:Response,_:Annotated[dict,Depends(festival_access)],user:Annotated[dict,Depends(roles("SUPER_ADMIN","FESTIVAL_MANAGER"))],connection:Annotated[Connection,Depends(database)],idempotency_key:Annotated[str|None,Header(alias="Idempotency-Key")]=None):
    if body.period.from_>=body.period.to:raise bad_request("VALIDATION_ERROR","보고 기간을 확인해 주세요.")
    def work():
        report=one(connection,"""INSERT INTO esg_reports(festival_id,title,period_from,period_to,compare_with_festival_id,format,created_by)
            VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *""",(festival_id,body.title,body.period.from_,body.period.to,body.compare_with_festival_id,body.format,user["id"]))
        job=one(connection,"INSERT INTO jobs(festival_id,job_type,resource_type,resource_id) VALUES(%s,'GENERATE_ESG_REPORT','ESG_REPORT',%s) RETURNING *",(festival_id,report["id"]))
        audit(connection,festival_id=festival_id,actor_id=str(user["id"]),action="GENERATE",resource_type="ESG_REPORT",resource_id=str(report["id"]),after_data={"jobId":str(job["id"])},request_id=request.state.request_id);return 202,{"reportId":report["id"],"jobId":job["id"],"status":"GENERATING"}
    return idempotent_success(request,response,idempotent(connection,key=idempotency_key,scope=f"esg-report:{festival_id}",body=body.model_dump(),work=work))


@router.get("/admin/festivals/{festival_id}/esg/reports/{report_id}")
def report(festival_id:str,report_id:str,request:Request,_:Annotated[dict,Depends(festival_access)],connection:Annotated[Connection,Depends(database)]):
    row=one(connection,"SELECT * FROM esg_reports WHERE id=%s AND festival_id=%s",(report_id,festival_id))
    if not row:raise not_found()
    return success(request,row)


@router.patch("/admin/festivals/{festival_id}/esg/reports/{report_id}")
def patch_report(festival_id:str,report_id:str,body:ReportPatch,request:Request,_:Annotated[dict,Depends(festival_access)],user:Annotated[dict,Depends(roles("SUPER_ADMIN","FESTIVAL_MANAGER"))],connection:Annotated[Connection,Depends(database)]):
    row=one(connection,"UPDATE esg_reports SET edit_metadata=%s,updated_at=now() WHERE id=%s AND festival_id=%s AND status='DRAFT' RETURNING *",(jsonb(body.edit_metadata),report_id,festival_id))
    if not row:raise bad_request("INVALID_STATE_TRANSITION","초안 보고서만 편집할 수 있습니다.")
    return success(request,row)


@router.post("/admin/festivals/{festival_id}/esg/reports/{report_id}/approve")
def approve_report(festival_id:str,report_id:str,request:Request,_:Annotated[dict,Depends(festival_access)],user:Annotated[dict,Depends(roles("SUPER_ADMIN","REVIEWER"))],connection:Annotated[Connection,Depends(database)]):
    row=one(connection,"UPDATE esg_reports SET status='APPROVED',updated_at=now() WHERE id=%s AND festival_id=%s AND status='DRAFT' RETURNING *",(report_id,festival_id))
    if not row:raise bad_request("INVALID_STATE_TRANSITION","초안 보고서만 승인할 수 있습니다.")
    return success(request,row)


@router.post("/admin/festivals/{festival_id}/esg/reports/{report_id}/exports",status_code=202)
def export_report(festival_id:str,report_id:str,body:ExportIn,request:Request,_:Annotated[dict,Depends(festival_access)],user:Annotated[dict,Depends(roles("SUPER_ADMIN","FESTIVAL_MANAGER"))],connection:Annotated[Connection,Depends(database)]):
    if not one(connection,"SELECT 1 FROM esg_reports WHERE id=%s AND festival_id=%s AND status='APPROVED'",(report_id,festival_id)):raise bad_request("INVALID_STATE_TRANSITION","승인된 보고서만 내보낼 수 있습니다.")
    job=one(connection,"""INSERT INTO jobs(festival_id,job_type,resource_type,resource_id,status,result)
        VALUES(%s,'EXPORT_ESG_REPORT','ESG_REPORT',%s,'COMPLETED',%s) RETURNING *""",(festival_id,report_id,jsonb({"format":body.format})))
    connection.execute("UPDATE esg_reports SET status='EXPORTED',updated_at=now() WHERE id=%s",(report_id,));return success(request,{"jobId":job["id"],"status":job["status"]})
