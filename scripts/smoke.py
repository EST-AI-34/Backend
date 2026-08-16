import os
import time

import httpx


BASE=os.getenv("API_URL","http://127.0.0.1:8000/api/v1")
FESTIVAL_CODE=os.getenv("FESTIVAL_CODE","EST34-2026")
client=httpx.Client(base_url=BASE,timeout=10)


def request(method:str,path:str,*,token:str|None=None,body:dict|None=None,headers:dict|None=None):
    merged=dict(headers or {})
    if token:merged["Authorization"]=f"Bearer {token}"
    response=client.request(method,path,json=body,headers=merged)
    if response.status_code>=400:raise RuntimeError(f"{response.status_code} {path}: {response.text}")
    return None if response.status_code==204 else response.json()["data"]


manager=request("POST","/auth/login",body={"email":"manager@example.com","password":"ChangeMe123!"})
reviewer=request("POST","/auth/login",body={"email":"reviewer@example.com","password":"ChangeMe123!"})
operator=request("POST","/auth/login",body={"email":"operator@example.com","password":"ChangeMe123!"})
manager_token=manager["accessToken"];reviewer_token=reviewer["accessToken"];operator_token=operator["accessToken"]
festivals=request("GET","/admin/festivals",token=manager_token)
# 아래 공개 조회가 전부 EST34-2026을 찍으므로 쓰기도 같은 축제에 해야 한다.
# festivals[0]을 쓰면 복제·테스트로 축제가 늘어난 DB에서 엉뚱한 축제에 쓰고 404가 난다.
festival_id=str(next(festival for festival in festivals if festival["code"]==FESTIVAL_CODE)["id"])
assert request("GET",f"/public/festivals/{FESTIVAL_CODE}")["status"]=="PUBLISHED"
assert any(program["slug"]=="family-craft" for program in request("GET",f"/public/festivals/{FESTIVAL_CODE}/programs"))

visitor=request("POST",f"/public/festivals/{FESTIVAL_CODE}/visitor-sessions",body={"language":"ko","accessibilityPreferences":{"largeText":True},"consents":{"analytics":False}})
visitor_token=visitor["sessionToken"]
conversation=request("POST","/visitor/ai/conversations",token=visitor_token,body={"festivalCode":FESTIVAL_CODE,"language":"ko"})
answer=request("POST",f"/visitor/ai/conversations/{conversation['id']}/messages",token=visitor_token,body={"message":"아이와 함께하는 가족 체험과 수유실을 알려줘."})
assert answer["safetyStatus"]=="ALLOWED" and answer["sources"]
surveys=request("GET",f"/public/festivals/{FESTIVAL_CODE}/surveys")
request("POST",f"/visitor/surveys/{surveys[0]['id']}/responses",token=visitor_token,body={"answers":[{"questionId":str(surveys[0]["questions"][0]["id"]),"value":5}]})

suffix=hex(time.time_ns())[2:]
area=request("POST",f"/admin/festivals/{festival_id}/areas",token=manager_token,body={"name":f"검증 구역 {suffix}","areaType":"TEST"})
program=request("POST",f"/admin/festivals/{festival_id}/programs",token=manager_token,body={"slug":f"smoke-{suffix}","title":"검증 프로그램","category":"test"})
request("POST",f"/admin/festivals/{festival_id}/programs/{program['id']}/sessions",token=manager_token,body={"areaId":str(area["id"]),"startsAt":"2026-09-13T01:00:00Z","endsAt":"2026-09-13T02:00:00Z","capacity":10})
item=request("POST",f"/admin/festivals/{festival_id}/content-items",token=manager_token,body={"contentType":"PROGRAM","resourceType":"PROGRAM","resourceId":str(program["id"]),"slug":f"smoke-{suffix}"})
version=request("POST",f"/admin/festivals/{festival_id}/content-items/{item['id']}/versions",token=manager_token,body={"language":"ko","body":{"title":"검증 프로그램","summary":"승인 게시 검증 콘텐츠"}})
request("POST",f"/admin/festivals/{festival_id}/content-versions/{version['id']}/submit",token=manager_token,body={})
request("POST",f"/admin/festivals/{festival_id}/content-versions/{version['id']}/reviews",token=reviewer_token,body={"decision":"APPROVED","comment":"검증 승인"})
request("POST",f"/admin/festivals/{festival_id}/content-items/{item['id']}/publish",token=manager_token,body={"versionId":str(version["id"])})
assert request("GET",f"/public/festivals/{FESTIVAL_CODE}/programs/{program['slug']}")["title"]=="검증 프로그램"

ticket=request("POST",f"/admin/festivals/{festival_id}/ops-tickets",token=manager_token,body={"ticketType":"INCIDENT","title":"검증 사고","description":"상태 전이 검증","priority":"HIGH","assigneeId":str(operator["user"]["id"])})
request("POST",f"/admin/festivals/{festival_id}/ops-tickets/{ticket['id']}/transitions",token=manager_token,body={"toStatus":"ASSIGNED"})
for status,note in (("IN_PROGRESS",None),("RESOLVED",None),("CLOSED","검증 완료")):
    request("POST",f"/admin/festivals/{festival_id}/ops-tickets/{ticket['id']}/transitions",token=operator_token,body={"toStatus":status,**({"note":note} if note else {})})

metric=request("POST",f"/admin/festivals/{festival_id}/esg/metrics",token=manager_token,body={"name":f"다회용기 반납 {suffix}","category":"E"})
metric_version=request("POST",f"/admin/festivals/{festival_id}/esg/metrics/{metric['id']}/versions",token=manager_token,body={"formula":"반납 로그 합계","unit":"개","sourceRequirements":{"type":"RETURN_LOG"},"evidenceRequired":True})
measurement=request("POST",f"/admin/festivals/{festival_id}/esg/measurements",token=manager_token,headers={"Idempotency-Key":f"measurement-{suffix}"},body={"metricVersionId":str(metric_version["id"]),"value":10,"sourceType":"REUSABLE_CUP_RETURN","dedupeKey":f"smoke-{suffix}","measuredAt":"2026-09-13T03:00:00Z"})
request("POST",f"/admin/festivals/{festival_id}/esg/measurements/{measurement['id']}/evidence",token=manager_token,body={"fileId":f"file-{suffix}","fileHash":f"sha256:{suffix}","evidenceType":"LOG"})
request("POST",f"/admin/festivals/{festival_id}/esg/measurements/{measurement['id']}/reviews",token=reviewer_token,body={"decision":"APPROVED","comment":"증빙 확인"})
report=request("POST",f"/admin/festivals/{festival_id}/esg/reports",token=manager_token,headers={"Idempotency-Key":f"report-{suffix}"},body={"title":"검증 보고서","period":{"from":"2026-09-01T00:00:00Z","to":"2026-10-01T00:00:00Z"},"format":"EDITABLE_DOCUMENT"})
time.sleep(1.5)
assert request("GET",f"/jobs/{report['jobId']}",token=manager_token)["status"]=="COMPLETED"
assert request("GET",f"/admin/festivals/{festival_id}/esg/reports/{report['reportId']}",token=manager_token)["status"]=="DRAFT"
print("smoke test passed: auth, public, visitor, AI, survey, approval, ticket, ESG report")
