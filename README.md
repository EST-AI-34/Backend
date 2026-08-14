# 지역축제 DX FastAPI 백엔드

Notion의 프로젝트 제안서, 기능 정의서, ERD, API 명세서를 바탕으로 구현한 1·2단계 백엔드입니다. FastAPI와 PostgreSQL 16을 사용합니다.

## 구현 범위

- 운영자 로그인, 액세스/리프레시 토큰 회전, 역할 및 축제 범위 권한
- 축제, 구역, 시설, 프로그램, 프로그램 회차 기준정보
- 콘텐츠 버전 작성 → 검수 요청 → 분리 승인 → 게시/게시 종료
- 공개 축제 홈, 프로그램, 지도, 시설, 공지, 설문
- 익명 방문 세션과 원문 토큰 해시 저장
- 승인·게시 콘텐츠만 사용하는 근거 기반 AI 검색, 안전 차단, 신고·검토
- 공지 예약/긴급 게시와 자동 만료 표시
- 민원·사고 티켓과 append-only 상태 전이 이벤트
- ESG 지표 버전, 실적 중복 방지, 증빙, 승인, 정정, 비동기 보고서 스냅샷
- 접근성 선호 저장과 축제 지원 언어 검증·기본 언어 대체
- 예약·모바일 대기표 발급, 호출, 취소, 노쇼와 정원 동시성 제어
- 수동·자동 혼잡 스냅샷, 최신 상태·오래된 값 표시, 운영 통합 대시보드
- 현장 인력 배치, 근무시간 충돌 차단과 배정 확인
- 참여업체 제출·승인·상인 소유 범위, 부스·메뉴·접근성 관리
- 쿠폰 발급·사용·취소, 수량·방문객 한도와 상권 성과 집계
- ESG 행동 인증, 중복·행동별·일일 한도 기반 포인트 원장
- 일정 충돌을 제외하는 맞춤 코스, 승인 ESG 성과 대시보드
- 권한 기반 운영 문서 검색·개인정보 마스킹, 민원 이슈 분류·담당자 수정
- 멱등성 키, 낙관적 버전 충돌 방지, 공통 오류/응답, 요청 추적, 감사 로그
- 혼잡·민원·인력·일정 신호를 규칙으로 합산한 운영자 위험 브리프 (AI-04)
- 승인 참여업체 기반 방문객 상권 추천과 광고 노출 분리, 노출 이력 기반 편향 점검 (BIZ-03)

결제·정산, AI 휴먼 키오스크, 센서·교통·관광 공급자별 연동과 예측은 3단계 범위라 포함하지 않았습니다. 외부 AI 제공자가 확정되지 않아 AI 답변은 승인 콘텐츠 또는 권한이 허용된 운영 문서의 보수적인 검색 결과만 반환합니다. 파일 저장소와 악성코드 검사 제공자도 미확정이므로 증빙 API는 완료된 외부 `fileId`와 해시를 연결합니다.

## 실행

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
- Readiness: `http://localhost:8000/health/ready`

데모 계정의 비밀번호는 모두 `ChangeMe123!`입니다.

| 역할 | 이메일 |
|---|---|
| 최고 관리자 | `admin@example.com` |
| 축제 담당자 | `manager@example.com` |
| 검토 담당자 | `reviewer@example.com` |
| 현장 운영자 | `operator@example.com` |
| 참여 상인 | `merchant@example.com` |

`scripts.seed`는 조직·운영자·상인 5명, `EST34-2026` 축제, 구역·시설, 게시 프로그램, 설문, 운영 티켓, E·S·G 승인 실적과 참여업체·쿠폰·혼잡·리워드·운영 문서를 중복 없이 생성합니다.

시드와 위 계정은 로컬 및 데모 환경 전용입니다. 실제 운영 환경에서는 시드를 실행하지 말고 강한 `JWT_SECRET`과 별도 계정 정책을 사용해야 합니다. 시드를 다시 실행하면 데모 계정 비밀번호가 위 기본값으로 갱신됩니다.

## Docker

애플리케이션 이미지는 저장소의 `Dockerfile`로 빌드합니다. PostgreSQL은 별도로 실행되어 있어야 하며 `DATABASE_URL`로 연결합니다.

```bash
docker build -t festival-dx-backend .
docker run --rm -p 8000:8000 --env-file .env \
  -e DATABASE_URL=postgres://festival:festival@host.docker.internal:5432/festival \
  festival-dx-backend
```

위 예시는 호스트에서 `docker compose up -d postgres`로 실행한 로컬 데이터베이스에 연결합니다.

## Railway 배포

`railway.toml`은 Dockerfile 빌드, 배포 전 마이그레이션, readiness 확인 및 실패 시 재시작을 설정합니다.

현재 데모 API: [https://backend-production-8532.up.railway.app](https://backend-production-8532.up.railway.app)

1. Railway 프로젝트에 PostgreSQL 서비스를 추가합니다.
2. 백엔드 서비스에 `DATABASE_URL`, `JWT_SECRET`, `ENVIRONMENT=production`을 설정합니다.
3. 필요하면 `.env.example`의 토큰·세션 만료 시간을 환경 변수로 재정의합니다.
4. 저장소를 연결해 배포합니다. 서버 포트는 Railway의 `PORT`를 자동으로 사용합니다.

운영 환경의 `JWT_SECRET`은 32자 이상이어야 합니다. 배포 과정에서는 마이그레이션만 자동 실행되며 `scripts.seed`는 실행되지 않습니다. 데모 데이터를 넣을 때만 대상 환경을 확인한 후 별도로 실행합니다.

## 검증

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q app scripts tests
API_URL=http://127.0.0.1:8000/api/v1 .venv/bin/python -m scripts.smoke
```

`tests/test_domain.py`는 DB 없이 도는 규칙·AI 클라이언트 테스트이고, `tests/test_api.py`는 `DATABASE_URL`이 가리키는 PostgreSQL에 마이그레이션과 데모 시드를 적용한 뒤 실제 엔드포인트를 호출합니다. DB에 접속할 수 없으면 API 테스트는 건너뜁니다(`docker compose up -d`로 띄운 뒤 실행하세요). 테스트도 시드를 쓰므로 운영 DB를 가리킨 채 실행하지 마세요.

`smoke`는 실행 중인 시드 서버를 대상으로 인증, 공개 조회, 익명 세션, AI, 설문, 콘텐츠 승인·게시, 티켓 전체 상태 전이, ESG 보고서 생성을 검증합니다.

> `scripts.smoke`는 읽기 전용 테스트가 아닙니다. 지정한 환경에 방문 세션, 설문 응답, 프로그램, 티켓, ESG 실적과 보고서를 생성하므로 로컬 또는 전용 데모 환경에서만 실행하세요.

## 주요 규칙

- 공개 API는 게시된 축제와 승인·게시된 콘텐츠만 반환합니다.
- 콘텐츠 작성자와 최종 승인자는 같을 수 없습니다.
- 티켓은 `OPEN → ASSIGNED → IN_PROGRESS → RESOLVED → CLOSED` 순서로 전이합니다.
- 승인 ESG 실적은 직접 수정할 수 없고 원본을 참조하는 새 실적으로 정정합니다.
- `audit_logs`는 데이터베이스 트리거로 수정과 삭제를 차단합니다.
- ESG 실적·보고서 생성은 `Idempotency-Key`가 필수입니다.
