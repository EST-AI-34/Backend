# Supabase POC DB Scope

This POC should not upload the full enterprise ERD first. The first Supabase
schema should cover only the screens and API flows currently used by FESTAI.

## Use This File

Run:

```text
db/supabase_poc_schema.sql
```

Keep:

- `db/migrations/001_init.sql` as the larger future ERD reference.
- `db/supabase_poc_schema.sql` as the actual POC upload target.

## Included Tables

Core festival data:

- `festivals`
- `festival_areas`
- `programs`
- `facilities`
- `stores`
- `coupons`
- `announcements`

Visitor and operation data:

- `visitor_sessions`
- `visitor_count_samples`
- `congestion_samples`
- `reservations`
- `ops_tickets`

Survey data:

- `surveys`
- `survey_questions`
- `survey_responses`
- `survey_answers`

ESG data:

- `esg_metrics`
- `esg_measurements`

AI conversation data:

- `ai_conversations`
- `ai_messages`

## Deferred From Full ERD

These are useful later but not required for the POC upload:

- organization/user/membership RBAC
- content approval/versioning workflow
- audit log immutability
- refresh token storage
- idempotency records
- evidence/review/report lifecycle tables for ESG
- AI message source/report moderation tables
- background jobs

## Data Responsibility

- Database stores source data.
- Backend validates data and calculates statistics.
- Alan/search retrieves relevant records.
- LLM converts verified results into natural language.
- LLM must not invent visitor counts, congestion, reservations, complaint
  trends, or ESG numbers.
