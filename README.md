# FESTAI 백엔드

운영자 콘솔, 방문객 QR 모바일 웹, 참여업체(상인) 콘솔이 사용하는 API를 제공하는 FastAPI 서비스입니다. 프로젝트 소개·기능 전반·기술 스택·아키텍처는 [FESTAI 프로젝트 개요](https://github.com/FEST-ON)를 참고하세요. 이 문서는 이 저장소를 돌리고 고치는 데 필요한 것만 다룹니다.

## 폴더 구조

```
app/
├── main.py                 # 앱 조립, 요청 추적·오류 변환, 레이트 리밋, 헬스체크, 라우터 등록
├── config.py / db.py / deps.py / errors.py / http.py / security.py / schemas.py
├── domain.py               # DB 없이 도는 규칙 — 상태 전이, 정원, 포인트 한도, 위험 브리프
├── ai.py                   # 승인 콘텐츠 기반 검색 응답, Alan 호출·폴백
├── context_repository.py   # AI가 참조하는 축제 컨텍스트 조회
├── preprocessing.py        # 노출 이력·집계 정규화
├── esg_export.py           # ESG 보고서 PDF·DOCX·CSV 산출
├── privacy.py              # 보유기간 파기, 동의·요구 처리
├── jobs.py                 # 비동기 잡 큐(재시도 3회)와 주기 정리
└── routes/                 # auth · public · visitor · p2_visitor · admin_core · admin_content
                            # admin_ops · admin_esg · p2_admin · insights · merchant
db/migrations/              # 001~010 스키마 마이그레이션
scripts/                    # migrate · seed · smoke · jeju_esg_2026 · 데모 데이터 SQL
tests/                      # 도메인·API·잡·SQL·전처리 테스트
voice/                      # CosyVoice 3 음성 합성 런타임 (별도 프로세스, README 참고)
```

## 엔드포인트 구성

| 영역 | 구현 내용 | 주요 경로 |
| --- | --- | --- |
| 인증·계정 | 로그인, 토큰 회전·재사용 탐지, 로그인 실패 잠금, 본인 비밀번호 변경(변경 시 리프레시 전면 폐기), 상인 초대 조회·수락 | `/auth/*`, `/me` |
| 기준정보 | 축제·구역·시설·프로그램·회차 CRUD, 축제 복제(회차는 시작일 차이만큼 이동, 프로그램은 DRAFT) | `/admin/festivals/*` |
| 콘텐츠 검수 | 버전 작성 → 검수 요청 → 분리 승인 → 게시·게시 종료, AI 답변 신고 검토 | `/admin/festivals/{id}/content-items`, `/ai/reviews` |
| 공개 조회 | 축제 홈·프로그램·구역·시설·지도·혼잡·공지·설문, 익명 방문 세션 발급(원문 토큰 해시 저장) | `/public/festivals/{code}/*` |
| 방문객 | 공지 열람, 설문 응답, 민원 접수, AI 대화·신고, 구역 식별(QR·수동, 2시간 유효), 접근성·언어 선호 저장, 키오스크 접근성 지표 | `/visitor/*`, `/visitor-sessions/current` |
| 예약·대기 | 회차 예약·모바일 대기표 발급·호출·취소·노쇼, 정원 동시성 제어 | `/visitor/bookings`, `/admin/festivals/{id}/bookings` |
| 현장 운영 | 혼잡 스냅샷(인원·대기·유효시간), 인력 배치·근무시간 충돌 차단·배정 확인, 통합 대시보드, 규칙 기반 위험 브리프 | `/crowd-snapshots`, `/staff-assignments`, `/dashboard`, `/risk-brief` |
| 티켓·공지 | 민원·사고 티켓과 append-only 상태 전이 이벤트, 안전·긴급 자동 분류와 담당자 수정, 공지 예약·긴급 게시·자동 만료, 구역 대상 선별과 도달 결과 | `/ops-tickets`, `/issue-analysis`, `/announcements`, `/notification-deliveries` |
| 설문 | 설문 등록·문항 구성·진행/종료, 익명 문항별 집계 | `/admin/festivals/{id}/surveys` |
| ESG | 지표 버전, 실적 중복 방지·증빙·승인·정정, 비동기 보고서 스냅샷·승인·내보내기, ESG 행동 인증과 포인트 원장, 승인 성과 대시보드 | `/esg/*`, `/reward-campaigns`, `/visitor/reward-events`, `/visitor/points` |
| 상권 | 참여업체 제출·승인·초대 링크(72시간) 기반 상인 계정, 부스·메뉴·접근성, 쿠폰 발행·사용·취소(수량·방문객 한도), 업체별 전환 지표, 상권 추천·광고 노출 분리와 편향 점검 | `/admin/festivals/{id}/businesses`, `/merchant/*`, `/business-recommendations`, `/recommendation-bias` |
| 조직·감사 | 멤버십·권한, 감사 로그(생성·수정·삭제 전부), CSV/JSON 내보내기 산출물, 잡 상태 조회 | `/admin/organizations/*`, `/audit-logs`, `/exports`, `/jobs/{id}` |
| 개인정보 | 항목별 수집 근거·보유기간 고지, 동의·철회(즉시 파기), 열람·삭제 요구 접수-처리 이력, 보유기간 정책표 기반 일 1회 연쇄 파기, 익명 식별자 재발급 이력 | `/visitor/privacy/*`, `/admin/festivals/{id}/privacy/*`, `/visitor-identity` |
| 운영 문서 | 권한 기반 문서 검색과 개인정보 마스킹 | `/internal-documents`, `/ai/operations/search` |

공통으로 깔린 것들:

- 멱등성 키(`Idempotency-Key`), 낙관적 버전 충돌 방지, 공통 오류·응답 포맷과 요청 추적
- 감사 로그·티켓·예약·ESG 실적의 키셋 커서 페이지네이션
- 경로별 레이트 리밋, `audit_logs` 수정·삭제를 막는 DB 트리거
- 잡 워커: 최대 3회 재시도, `FOR UPDATE SKIP LOCKED`, 만료 멱등성 레코드·리프레시 토큰·방문 세션·추천 노출 이력 주기 정리

### 범위 밖

결제·정산, AI 휴먼 키오스크, 센서 기반 자동 혼잡 수집, 교통·관광 공급자별 연동과 예측은 3단계 범위라 포함하지 않았습니다. 파일 저장소와 악성코드 검사 제공자가 미확정이므로 ESG 증빙 API는 완료된 외부 `fileId`와 해시를 연결합니다.

## 실행 방법

요구 사항은 Python 3.12 이상과 Docker입니다.

```bash
cp .env.example .env
docker compose up -d postgres
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m scripts.migrate
.venv/bin/python -m scripts.seed
.venv/bin/uvicorn app.main:app --reload
```

- API: `http://localhost:8000/api/v1`
- Swagger UI: `http://localhost:8000/docs`
- OpenAPI: `http://localhost:8000/openapi.json`
- Liveness: `http://localhost:8000/health/live`
- Readiness: `http://localhost:8000/health/ready` (DB 연결까지 확인)

데모 계정의 비밀번호는 모두 `ChangeMe123!`입니다.

| 역할 | 이메일 |
| --- | --- |
| 최고 관리자 | `admin@example.com` |
| 축제 담당자 | `manager@example.com` |
| 검토 담당자 | `reviewer@example.com` |
| 현장 운영자 | `operator@example.com` |
| 참여 상인 | `merchant@example.com` |

`scripts.seed`는 조직·운영자·상인 5명, `EST34-2026` 축제, 구역·시설, 게시 프로그램, 설문, 운영 티켓, E·S·G 승인 실적과 참여업체·쿠폰·혼잡·리워드·운영 문서를 중복 없이 생성합니다. 데모 데이터를 더 채울 때는 다음을 씁니다.

```bash
.venv/bin/python -m scripts.jeju_esg_2026          # 드라이런(롤백), --apply로 커밋
psql "$DATABASE_URL" -f scripts/est34_2026_demo_enrichment.sql   # EST34-2026 운영 데이터 보강
psql "$DATABASE_URL" -f scripts/allen_demo_data.sql              # ALLEN-DEMO-2026 샌드박스 축제
```

시드와 위 계정은 로컬 및 데모 환경 전용입니다. 실제 운영 환경에서는 시드를 실행하지 말고 강한 `JWT_SECRET`과 별도 계정 정책을 사용해야 합니다. 시드를 다시 실행하면 데모 계정 비밀번호가 위 기본값으로 갱신됩니다.

## 환경 변수

`.env.example`을 복사해 사용합니다. 값은 모두 선택이며 아래가 기본값입니다.

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `DATABASE_URL` | `postgres://festival:festival@localhost:5432/festival` | PostgreSQL 연결 문자열 |
| `JWT_SECRET` | 개발용 기본값 | 운영에서는 32자 이상 필수 |
| `ACCESS_TOKEN_MINUTES` / `REFRESH_TOKEN_DAYS` | `15` / `7` | 토큰 만료 |
| `VISITOR_SESSION_HOURS` | `24` | 익명 방문 세션 만료 |
| `ENVIRONMENT` | `development` | `production`이면 시크릿 검증이 엄격해집니다 |
| `TRUST_PROXY_HEADERS` | 비우면 PaaS 표식(Railway·Vercel)이 있을 때만 자동 | 레이트 리밋 IP를 `X-Forwarded-For`에서 읽을지 여부 |
| `LOGIN_MAX_FAILURES` / `LOGIN_LOCK_MINUTES` | `5` / `5` | 로그인 실패 잠금 |
| `ENABLE_EXTERNAL_AI` | `false` | 끄면 외부 호출 없이 규칙 문장과 승인 콘텐츠 요약만 사용 |
| `ALAN_QUESTION_URL` / `ALAN_CLIENT_ID` | Alan 기본 URL / 없음 | 발급받은 UUID는 커밋하지 말고 배포 환경변수로 주입 |
| `ALAN_CONNECT_TIMEOUT_SECONDS` / `ALAN_READ_TIMEOUT_SECONDS` / `ALAN_MAX_RETRIES` | `3` / `8` / `1` | Alan 호출 타임아웃·재시도 |
| `ALAN_LOCK_WAIT_SECONDS` | `2` | client_id 하나를 공유해 호출이 직렬입니다. 이만큼 못 기다리면 규칙 문장으로 응답 |
| `BRIEFING_CACHE_SECONDS` | `120` | 같은 신호에는 같은 브리핑 문장을 재사용 |
| `IDEMPOTENCY_RETENTION_DAYS` / `VISITOR_SESSION_RETENTION_DAYS` | `7` / `180` | 잡 워커가 지우는 만료 데이터 보존 기간 |
| `RECOMMENDATION_EVENT_RETENTION_DAYS` | `180` | 편향 점검 조회 창(최대 90일)보다 짧게 두지 말 것 |

## 검증

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q app scripts tests
API_URL=http://127.0.0.1:8000/api/v1 .venv/bin/python -m scripts.smoke
```

`tests/test_domain.py`·`test_preprocessing.py`·`test_jobs.py`·`test_ai_festival_context.py`는 DB 없이 도는 규칙·집계·AI 클라이언트 테스트이고, `tests/test_api.py`·`test_patch_endpoints.py`·`test_sql_queries.py`는 `DATABASE_URL`이 가리키는 PostgreSQL에 마이그레이션과 데모 시드를 적용한 뒤 실제 엔드포인트를 호출합니다. DB에 접속할 수 없으면 API 테스트는 건너뜁니다(`docker compose up -d`로 띄운 뒤 실행하세요). 테스트도 시드를 쓰므로 운영 DB를 가리킨 채 실행하지 마세요.

`smoke`는 실행 중인 시드 서버를 대상으로 인증, 공개 조회, 익명 세션, AI, 설문, 콘텐츠 승인·게시, 티켓 전체 상태 전이, ESG 보고서 생성을 검증합니다.

> `scripts.smoke`는 읽기 전용 테스트가 아닙니다. 지정한 환경에 방문 세션, 설문 응답, 프로그램, 티켓, ESG 실적과 보고서를 생성하므로 로컬 또는 전용 데모 환경에서만 실행하세요.

## 배포

### Docker

애플리케이션 이미지는 저장소의 `Dockerfile`로 빌드합니다. PostgreSQL은 별도로 실행되어 있어야 하며 `DATABASE_URL`로 연결합니다.

```bash
docker build -t festival-dx-backend .
docker run --rm -p 8000:8000 --env-file .env \
  -e DATABASE_URL=postgres://festival:festival@host.docker.internal:5432/festival \
  festival-dx-backend
```

위 예시는 호스트에서 `docker compose up -d postgres`로 실행한 로컬 데이터베이스에 연결합니다.

### Railway

`railway.toml`은 Dockerfile 빌드, 배포 전 마이그레이션, `/health/ready` 확인 및 실패 시 재시작(최대 10회)을 설정합니다.

현재 데모 API: [https://backend-production-8532.up.railway.app](https://backend-production-8532.up.railway.app)

1. Railway 프로젝트에 PostgreSQL 서비스를 추가합니다.
2. 백엔드 서비스에 `DATABASE_URL`, `JWT_SECRET`, `ENVIRONMENT=production`을 설정합니다.
3. 필요하면 위 환경 변수 표의 값을 재정의합니다.
4. 저장소를 연결해 배포합니다. 서버 포트는 Railway의 `PORT`를 자동으로 사용합니다.

운영 환경의 `JWT_SECRET`은 32자 이상이어야 합니다. 배포 과정에서는 마이그레이션만 자동 실행되며 `scripts.seed`는 실행되지 않습니다. 데모 데이터를 넣을 때만 대상 환경을 확인한 후 별도로 실행합니다.

## 주요 규칙

- 공개 API는 게시된 축제와 승인·게시된 콘텐츠만 반환합니다.
- 콘텐츠 작성자와 최종 승인자는 같을 수 없습니다. 작성자는 자신이 만든 콘텐츠와 ESG 보고서를 최종 승인할 수 없습니다(공지 제외).
- 티켓은 `OPEN → ASSIGNED → IN_PROGRESS → RESOLVED → CLOSED` 순서로 전이합니다.
- 승인 ESG 실적은 직접 수정할 수 없고 원본을 참조하는 새 실적으로 정정합니다. ESG 실적·보고서 생성은 `Idempotency-Key`가 필수입니다.
- 일일 포인트 한도는 캠페인별로 따로 셉니다.
- `audit_logs`는 데이터베이스 트리거로 수정과 삭제를 차단합니다.
- `festival_areas`·`facilities`·`programs`·`program_sessions`의 `status`는 DB CHECK 제약으로 값이 고정됩니다.
- 방문객 연락처는 저장하지 않습니다. 복호화 경로 없이 JWT 서명 키로 암호화하던 컬럼은 제거했습니다.
- 키오스크 연령대 추정 결과는 축제·이벤트 종류·모델 버전·시각만 남기고 어떤 세션인지는 저장하지 않습니다.
- AI 방문객 답변은 승인·게시 콘텐츠가 검색된 경우에만 생성하고, Alan 실패 시 규칙 문장으로 대체하며 `externalAiUsed`로 외부 사용 여부를 표시합니다.

## 알려진 한계

- ESG 보고서 PDF는 외부 폰트 임베딩 없이 표준 14폰트(Latin-1)로만 그려서 한글이 `?`로 깨집니다.
  한글이 그대로 필요하면 DOCX로 내보내세요. 서버가 `textLossWarning`으로 손실 여부를 알려 줍니다.
- 레이트 리밋과 로그인 잠금 카운터는 프로세스 로컬입니다. API 인스턴스를 늘리면 Redis 등 공유 저장소로 옮겨야 합니다.
- 레이트 리밋은 프록시(Railway·Vercel) 표식이 있으면 `X-Forwarded-For`를 자동으로 신뢰합니다.
  직결 배포에서는 `TRUST_PROXY_HEADERS=false`로 두세요 — 켜면 클라이언트가 헤더를 위조해 한도를 우회할 수 있습니다.
- 리워드 QR 인증은 등록한 `rule.verificationKeys` 값과 대조합니다. QR 발급·인쇄는 운영 도구 범위 밖입니다.
- 음성 합성(`voice/`)은 CosyVoice 저장소와 GPU 가중치를 직접 준비해야 하는 선택 런타임입니다. 없으면 프론트가 브라우저 내장 음성으로 대체합니다.
- 잡 워커는 API 프로세스 안의 데몬 스레드입니다. 인스턴스가 여러 개면 `FOR UPDATE SKIP LOCKED`로
  중복 처리는 막히지만, 전용 워커가 필요해지면 분리해야 합니다.
