# Frontend Integration: AI-04 and BIZ-03

All API responses use the existing envelope:

```json
{
  "data": {},
  "meta": {
    "requestId": "req_...",
    "serverTime": "2026-08-12T00:00:00+00:00"
  }
}
```

## Admin Authorization

Admin endpoints require:

```http
Authorization: Bearer <HS256 JWT>
```

The JWT payload must contain:

```json
{
  "sub": "user-id",
  "role": "FESTIVAL_MANAGER",
  "festival_scope": ["EST34-2026"]
}
```

Allowed admin roles are `SUPER_ADMIN`, `FESTIVAL_MANAGER`, `FIELD_OPERATOR`,
and `REVIEWER`. Use `festival_scope: ["*"]` only for global admin accounts.

## AI-04 Risk Brief

Request:

```http
GET /api/v1/admin/festivals/EST34-2026/risk-brief?refresh=false&include_resolved=false
```

Response fields in `data`:

```json
{
  "festival_id": "EST34-2026",
  "risk_level": "warning",
  "risk_score": 60,
  "summary": "Risk is warning with score 60 based on verified signals: crowding.",
  "evidence": [
    {
      "type": "crowding",
      "value": 1,
      "threshold": 0,
      "source_updated_at": "2026-08-12T23:00:00+09:00"
    }
  ],
  "reasons": ["crowding value 1 was compared with threshold 0."],
  "operator_notes": ["This score is rule-based; verify field conditions before public notices."],
  "recommended_actions": ["Add safety staff to the crowded area and guide visitors to alternate routes."],
  "generated_at": "2026-08-12T23:01:00+09:00",
  "source_updated_at": "2026-08-12T23:00:00+09:00",
  "external_ai_used": false,
  "fallback_used": true,
  "policy_version": "risk-v1"
}
```

Risk levels are `normal`, `warning`, `critical`, and `insufficient_data`.

## BIZ-03 Business Recommendations

Request:

```http
GET /api/v1/visitor/festivals/EST34-2026/business-recommendations?latitude=37.5260&longitude=126.9350&category=restaurant&limit=10&accessibility_required=false
```

Rules:

- `latitude` and `longitude` must be sent together.
- `latitude`: `-90..90`
- `longitude`: `-180..180`
- `limit`: `1..50`
- `category`: `restaurant`, `cafe`, `market`, or `souvenir`

Response fields in `data`:

```json
{
  "festival_id": "EST34-2026",
  "items": [
    {
      "business_id": "BIZ-...",
      "name": "Local Business",
      "score": 0.75,
      "reasons": ["Currently open.", "Coupon benefit is available."],
      "is_sponsored": false,
      "operating_status": "open",
      "distance_meters": 22,
      "category": "restaurant",
      "location_id": "area-id"
    }
  ],
  "sponsored_items": [],
  "recommendation_policy_version": "biz-rec-v1",
  "generated_at": "2026-08-12T23:10:00+09:00"
}
```

Render `items` and `sponsored_items` separately. If both arrays are empty, show
an empty state instead of demo data.
