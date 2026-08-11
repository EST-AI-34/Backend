# AI Agent Allen Report Check

## Scope

The original `C:\Users\yeoh0\ai-agent` folder must not be edited. Submission
changes are isolated in `C:\Users\yeoh0\festai\_deliverables\ai-agent-allen-only`.

## Existing Pipeline

`ai-agent` already has this report pipeline:

```text
payload -> score -> risk -> responsibility -> report -> PDF
```

The PDF connection remains:

```text
run_audit_pipeline() -> generate_pdf(result["report"], ...)
```

## Final API Direction

The target service is ESTsoft myAlan:

```text
https://myalan.ai
https://api.myalan.ai/openapi.json
```

Use the channel/message API:

```text
POST /api/v1/channels
POST /api/v1/channels/{channel_id}/messages
GET  /api/v1/channels/{channel_id}/messages
```

Use only:

```text
ALLEN_AUTH_MODE=bearer
Authorization: Bearer ${ALLEN_API_KEY}
ALLEN_PERSONA_ID=69ce0aeab459faf50a427005
```

Development POC mode may use:

```text
ALLEN_AUTH_MODE=implicit
ALLEN_CLIENT_ID=<fixed non-secret device/client identifier>
```

`ALLEN_API_KEY` must not be sent as the implicit `client_id`, and the backend
must not automatically switch auth modes after a failure.

Do not use:

- OpenRouter
- Gemini
- GPT/Claude personas
- local report fallback generation

## Status

Backend ESG one-line briefing code is implemented with bounded polling and
clear Allen errors. Live approval still requires an official myAlan Bearer token
for bearer mode, or an explicit POC `ALLEN_CLIENT_ID` for implicit mode, that can
create channels with the fixed Alan v4.0 persona.

Current non-official local token result:

```text
POST /api/v1/channels -> 307 login redirect
```
