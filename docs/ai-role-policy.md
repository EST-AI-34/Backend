# Alan AI and LLM Role Policy

FESTAI must not treat Alan AI or any general LLM as the source of truth for
festival operation data. AI is a conversational interface over verified data,
not the owner of raw data, statistics, or final operational decisions.

## Core Data Flow

```text
Data collection
-> Database storage
-> Backend validation and analytics
-> Alan AI or search tool retrieval
-> LLM answer composition
-> Screen or voice response
```

## Role Boundaries

| Layer | Responsibility |
| --- | --- |
| Database | Stores source data such as visitors, congestion, reservations, complaints, programs, notices, and ESG records. |
| Backend | Validates data, calculates statistics, exposes verified API results, and blocks unsupported claims. |
| Alan AI / Search | Retrieves relevant information from approved data sources. It does not own, store, or finalize analytics. |
| Allen LLM | Converts retrieved search/API results into natural language answers using prompt rules. |
| Frontend | Handles text/voice input, displays answers, and falls back to keyboard input when voice recognition is weak. |
| Admin pages | Manage source data, operating status, review history, and approved statistics. |

## Admin ESG Briefing

The admin ESG one-line briefing uses this narrower flow:

```text
ESG metrics from database/repository
-> Backend summary/context construction
-> Allen-only one-line briefing generation
-> Admin dashboard display
```

Allen receives only verified ESG context prepared by the backend. It must not
query arbitrary sources, calculate new ESG scores, or switch to another model.
If Allen is unavailable, the API returns a clear provider error.

## LLM Guardrails

- Do not ask Alan AI or an LLM to store original operation data.
- Do not let an LLM invent visitor counts, congestion values, reservation counts, complaint trends, ESG numbers, or rankings.
- Use only database/API results for statistics and analysis.
- If verified data is missing, answer that the information is not available and guide the user to official staff/notices.
- Keep sources attached to answers whenever possible.
- Separate retrieval from answer generation: search first, then compose.
- If Allen fails, return a clear provider error instead of switching to another model.

## Recommended AI Processing Flow

```text
User question
-> STT, if voice input is used
-> Intent classification
-> Retrieve related data with Alan AI or search
-> Fetch verified records/statistics from database/API
-> Compose the final answer with Allen LLM
-> Display the answer or read it aloud
```

## Voice Recognition Scope

Festival sites are noisy because of performances, announcements, and visitor
conversation. Production voice support should consider noise suppression, VAD,
directional microphones, domain vocabulary, proper-noun correction, confidence
thresholds, clarification questions, expected-question correction, keyboard
input handoff, and user confirmation before answering.

For the current POC, the scope is only to prove that voice-based guidance works.
Advanced noise cancellation and STT accuracy improvements should remain a
production-stage technical task.
