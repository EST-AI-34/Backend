import math
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.repositories.ai_repository import AIRepository, AllenAPIError
from app.repositories.festival_repository import FestivalRepository
from app.repositories.insights_repository import InsightsRepository
from app.schemas.insights import (
    BusinessRecommendationItem,
    BusinessRecommendations,
    RecommendationBiasAudit,
    RecommendationBiasBusinessExposure,
    RecommendationBiasCategoryExposure,
    RiskBrief,
    RiskEvidence,
)


KST = ZoneInfo("Asia/Seoul")


class InsightsService:
    def __init__(self) -> None:
        self.repo = InsightsRepository()
        self.festival_repo = FestivalRepository()
        self.ai_repo = AIRepository()

    def get_risk_brief(
        self,
        festival_id: str,
        refresh: bool = False,
        include_resolved: bool = False,
    ) -> RiskBrief:
        if not refresh:
            saved = self.repo.get_risk_brief(festival_id, include_resolved)
            if saved:
                return RiskBrief(**saved)

        signals = self.repo.list_risk_signals(festival_id, include_resolved)
        now = datetime.now(KST)
        if not signals:
            payload = {
                "festival_id": festival_id,
                "risk_level": "insufficient_data",
                "risk_score": 0,
                "summary": "There is not enough verified operations data to judge festival risk.",
                "evidence": [],
                "reasons": ["No crowding, complaint, schedule, staffing, or safety signals were available."],
                "operator_notes": ["Collect current operations data before making a risk decision."],
                "recommended_actions": ["Check field reports and update operations records."],
                "generated_at": now,
                "source_updated_at": None,
                "external_ai_used": False,
                "fallback_used": True,
                "policy_version": "risk-v1",
            }
            return RiskBrief(**self.repo.save_risk_brief(festival_id, include_resolved, payload))

        evidence = [
            RiskEvidence(
                type=item["type"],
                value=item["value"],
                threshold=item.get("threshold"),
                source_updated_at=item.get("source_updated_at") or now,
            )
            for item in signals
        ]
        risk_score = min(100, sum(self._signal_points(item) for item in signals))
        risk_level = self._risk_level(risk_score)
        source_updated_at = max(item.source_updated_at for item in evidence)
        summary = self._risk_summary(risk_level, risk_score, signals)
        external_ai_used = False
        fallback_used = True

        if settings.ENABLE_EXTERNAL_AI:
            try:
                summary = self.ai_repo.create_risk_briefing(self._risk_context(signals))["briefing"]
                external_ai_used = True
                fallback_used = False
            except AllenAPIError:
                external_ai_used = False
                fallback_used = True

        payload = {
            "festival_id": festival_id,
            "risk_level": risk_level,
            "risk_score": risk_score,
            "summary": summary,
            "evidence": [item.model_dump() for item in evidence],
            "reasons": self._risk_reasons(signals),
            "operator_notes": ["This score is rule-based; verify field conditions before public notices."],
            "recommended_actions": self._risk_actions(signals),
            "generated_at": now,
            "source_updated_at": source_updated_at,
            "external_ai_used": external_ai_used,
            "fallback_used": fallback_used,
            "policy_version": "risk-v1",
        }
        return RiskBrief(**self.repo.save_risk_brief(festival_id, include_resolved, payload))

    def recommend_businesses(
        self,
        festival_id: str,
        latitude: float | None = None,
        longitude: float | None = None,
        category: str | None = None,
        limit: int = 10,
        accessibility_required: bool = False,
    ) -> BusinessRecommendations:
        candidates = self.repo.list_business_candidates(festival_id)
        if candidates is None:
            candidates = [
                self._fixture_business(item)
                for item in self.festival_repo.list_stores()
                if str(festival_id) in {"1", "EST34-2026"} and item.get("festival_id") == 1
            ]

        filtered = [
            item
            for item in candidates
            if item.get("operating_status") == "open"
            and (not category or item.get("category") == category)
            and (not accessibility_required or item.get("accessible"))
        ]
        scored = [self._score_business(item, latitude, longitude, category) for item in filtered]
        scored.sort(key=lambda item: (-item.score, item.business_id))
        response = BusinessRecommendations(
            festival_id=festival_id,
            items=[item for item in scored if not item.is_sponsored][:limit],
            sponsored_items=[item for item in scored if item.is_sponsored][:limit],
            recommendation_policy_version="biz-rec-v1",
            generated_at=datetime.now(KST),
        )
        self.repo.log_recommendation_event(
            {
                "festival_id": festival_id,
                "request": {
                    "latitude": latitude,
                    "longitude": longitude,
                    "category": category,
                    "limit": limit,
                    "accessibility_required": accessibility_required,
                },
                "response": response.model_dump(),
                "policy_version": response.recommendation_policy_version,
            }
        )
        return response

    def audit_recommendation_bias(
        self,
        festival_id: str,
        window_days: int = 7,
        max_business_share: float = 0.6,
        max_category_share: float = 0.75,
        min_events: int = 1,
    ) -> RecommendationBiasAudit:
        events = self.repo.list_recommendation_events(festival_id, window_days)
        business_counts: Counter[str] = Counter()
        general_counts: Counter[str] = Counter()
        sponsored_counts: Counter[str] = Counter()
        category_counts: Counter[str] = Counter()
        business_meta: dict[str, dict[str, str]] = {}

        for event in events:
            response = event.get("response") or {}
            for section, is_sponsored_section in (("items", False), ("sponsored_items", True)):
                for item in response.get(section, []) or []:
                    business_id = str(item.get("business_id") or item.get("id") or "")
                    if not business_id:
                        continue
                    category = str(item.get("category") or "unknown")
                    name = str(item.get("name") or business_id)
                    is_sponsored = bool(item.get("is_sponsored", is_sponsored_section))
                    business_counts[business_id] += 1
                    category_counts[category] += 1
                    business_meta[business_id] = {"name": name, "category": category}
                    if is_sponsored:
                        sponsored_counts[business_id] += 1
                    else:
                        general_counts[business_id] += 1

        total_exposures = sum(business_counts.values())
        general_exposures = sum(general_counts.values())
        sponsored_exposures = sum(sponsored_counts.values())
        generated_at = datetime.now(KST)

        business_rows = [
            RecommendationBiasBusinessExposure(
                business_id=business_id,
                name=business_meta[business_id]["name"],
                category=business_meta[business_id]["category"],
                total_exposures=count,
                general_exposures=general_counts[business_id],
                sponsored_exposures=sponsored_counts[business_id],
                exposure_share=round(count / total_exposures, 4) if total_exposures else 0,
                is_over_threshold=(count / total_exposures) > max_business_share if total_exposures else False,
            )
            for business_id, count in business_counts.most_common()
        ]
        category_rows = [
            RecommendationBiasCategoryExposure(
                category=category,
                total_exposures=count,
                exposure_share=round(count / total_exposures, 4) if total_exposures else 0,
                is_over_threshold=(count / total_exposures) > max_category_share if total_exposures else False,
            )
            for category, count in category_counts.most_common()
        ]
        over_business = [row for row in business_rows if row.is_over_threshold]
        over_category = [row for row in category_rows if row.is_over_threshold]

        if len(events) < min_events or total_exposures == 0:
            status = "insufficient_data"
            summary = "Not enough recommendation exposure events are available for bias review."
            actions = ["Run this audit after recommendation traffic is collected."]
        elif over_business or over_category:
            status = "warning"
            summary = "Recommendation exposure concentration exceeded the configured bias threshold."
            actions = [
                "Review businesses or categories over threshold before the next weekly check.",
                "Adjust recommendation policy or exposure rotation if concentration is not justified by filters.",
            ]
        else:
            status = "pass"
            summary = "No business or category exceeded the configured recommendation exposure thresholds."
            actions = ["Continue weekly recommendation bias checks."]

        return RecommendationBiasAudit(
            festival_id=festival_id,
            status=status,
            summary=summary,
            checked_event_count=len(events),
            total_exposures=total_exposures,
            general_exposures=general_exposures,
            sponsored_exposures=sponsored_exposures,
            business_exposures=business_rows,
            category_exposures=category_rows,
            thresholds={
                "max_business_exposure_share": max_business_share,
                "max_category_exposure_share": max_category_share,
                "min_events": min_events,
            },
            recommended_actions=actions,
            window_days=window_days,
            generated_at=generated_at,
            next_recommended_check_at=generated_at + timedelta(days=7),
        )

    def _signal_points(self, signal: dict) -> int:
        signal_type = signal["type"]
        value = float(signal["value"])
        threshold = float(signal.get("threshold") or 0)
        if signal_type == "crowding":
            return 45 if value >= 90 else 30 if value >= threshold else 10
        if signal_type == "unresolved_safety_complaints":
            return 30 if value > threshold else 15
        if signal_type == "schedule_change":
            return 20
        if signal_type == "staffing_gap":
            return 25 if value > threshold else 10
        return 10

    def _risk_level(self, score: int) -> str:
        if score >= 75:
            return "critical"
        if score >= 40:
            return "warning"
        return "normal"

    def _risk_summary(self, risk_level: str, score: int, signals: list[dict]) -> str:
        top = ", ".join(item["type"] for item in signals[:3])
        return f"Risk is {risk_level} with score {score} based on verified signals: {top}."

    def _risk_reasons(self, signals: list[dict]) -> list[str]:
        return [
            f"{item['type']} value {item['value']} was compared with threshold {item.get('threshold')}."
            for item in signals
        ]

    def _risk_actions(self, signals: list[dict]) -> list[str]:
        signal_types = {item["type"] for item in signals}
        actions = []
        if "crowding" in signal_types:
            actions.append("Add safety staff to the crowded area and guide visitors to alternate routes.")
        if "unresolved_safety_complaints" in signal_types:
            actions.append("Resolve open safety complaints before lowering the risk level.")
        if "staffing_gap" in signal_types:
            actions.append("Reassign reserve staff to the affected area.")
        if "schedule_change" in signal_types:
            actions.append("Confirm changed schedules with field operators before publishing visitor notices.")
        return actions or ["Continue monitoring verified operations signals."]

    def _risk_context(self, signals: list[dict]) -> list[str]:
        return [
            f"type={item['type']};value={item['value']};threshold={item.get('threshold')};updated_at={item.get('source_updated_at')}"
            for item in signals
        ]

    def _fixture_business(self, item: dict) -> dict:
        return {
            **item,
            "latitude": None,
            "longitude": None,
            "operating_status": "open",
            "is_sponsored": item.get("id") == 2,
            "accessible": True,
            "esg_participating": False,
        }

    def _score_business(
        self,
        business: dict,
        latitude: float | None,
        longitude: float | None,
        category: str | None,
    ) -> BusinessRecommendationItem:
        score = 0.25
        reasons = ["Currently open."]
        if category and business["category"] == category:
            score += 0.25
            reasons.append("Matches the requested category.")
        if business.get("coupon_available"):
            score += 0.15
            reasons.append("Coupon benefit is available.")
        if business.get("esg_participating"):
            score += 0.10
            reasons.append("Participates in ESG/local program.")
        distance = self._distance_meters(latitude, longitude, business.get("latitude"), business.get("longitude"))
        if distance is not None:
            score += max(0.0, 0.25 * (1 - min(distance, 1000) / 1000))
            reasons.append("Near the current visitor location.")
        return BusinessRecommendationItem(
            business_id=f"BIZ-{business['id']}",
            name=business["name"],
            score=round(min(score, 1.0), 2),
            reasons=reasons,
            is_sponsored=bool(business.get("is_sponsored")),
            operating_status=business["operating_status"],
            distance_meters=distance,
            category=business["category"],
            location_id=business.get("location_id"),
        )

    def _distance_meters(
        self,
        lat1: float | None,
        lon1: float | None,
        lat2: float | None,
        lon2: float | None,
    ) -> int | None:
        if None in {lat1, lon1, lat2, lon2}:
            return None
        radius = 6371000
        phi1 = math.radians(float(lat1))
        phi2 = math.radians(float(lat2))
        delta_phi = math.radians(float(lat2) - float(lat1))
        delta_lambda = math.radians(float(lon2) - float(lon1))
        hav = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
        return round(radius * 2 * math.atan2(math.sqrt(hav), math.sqrt(1 - hav)))
