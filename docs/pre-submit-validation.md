# Pre-submit Validation

## Secret Scan

Checked paths:

```text
C:\Users\yeoh0\festai\_deliverables\Backend-repo-allen-only
C:\Users\yeoh0\festai\_deliverables\ai-agent-allen-only
```

Result:

```text
No real secret value was found.
Only environment-variable reads and placeholder examples were matched.
```

## Supabase SQL Check

File:

```text
Backend-repo/db/supabase_poc_schema.sql
```

Validation:

```text
Open Supabase connection from backend/.env DATABASE_URL
BEGIN
Execute POC schema SQL
Check visible POC tables
ROLLBACK
```

Result:

```text
poc_table_count_visible_in_tx=20
supabase_sql_transaction_check=ok
```

## myAlan API Check

Target service:

```text
https://myalan.ai
https://api.myalan.ai/openapi.json
```

Final backend flow:

```text
POST /api/v1/channels
POST /api/v1/channels/{channel_id}/messages
GET  /api/v1/channels/{channel_id}/messages
```

Final authentication rule:

```text
ALLEN_AUTH_MODE=bearer
-> Authorization: Bearer ${ALLEN_API_KEY}
```

Development POC authentication rule:

```text
ALLEN_AUTH_MODE=implicit
-> device-info + oauth2/token using ${ALLEN_CLIENT_ID}
```

`ALLEN_API_KEY` is never reused as an implicit `client_id`. The backend does not
fall back between `bearer` and `implicit`; each mode must be selected and
validated explicitly.

Fixed persona:

```text
ALLEN_PERSONA_ID=69ce0aeab459faf50a427005
persona=Alan v4.0
```

Disallowed personas:

```text
GPT-5
Claude
Gemini
OpenRouter
```

## Admin ESG Briefing Check

Endpoint:

```text
GET /api/v1/esg/briefing
```

Expected flow:

```text
ESG repository metrics
-> backend ESG summary/context
-> myAlan channel/message API
-> poll bounded attempts for assistant content
-> one-line Korean admin briefing
```

Polling limits:

```text
ALLEN_MESSAGE_POLL_SECONDS=2
ALLEN_MESSAGE_POLL_ATTEMPTS=20
```

Test coverage:

```text
4 passed
```

The current local `backend/.env` value is not a verified official Bearer access
token, so bearer-mode operation still requires replacing `ALLEN_API_KEY` with a
provider-issued token that can create myAlan channels.

Latest official Bearer-mode live check:

```text
alan_live=false
status_code=502
provider_status_code=307
meaning=myAlan redirected the channel creation request to login
```

This is expected with the current non-official token value. The final code does
not automatically bypass this with another auth mode.
