from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from .schemas import AiRouteExplanation, AiRoutePlanRequest


FORBIDDEN_CLAIMS = (
    "안전 보장",
    "위험 없음",
    "공사 없음",
    "통제 없음",
    "노면 문제 없음",
    "완전히 안전",
)


def build_preference_context(request: AiRoutePlanRequest) -> dict:
    labels = {
        "SCENERY_FIRST": "경치 우선",
        "BIKE_PATH_FIRST": "자전거도로 우선",
    }
    return {
        "destinationLabel": request.destinationLabel,
        "rideStyle": request.rideStyle,
        "primaryLens": labels.get(request.rideStyle or "", "균형형"),
        "preferenceSummary": request.preferenceSummary,
        "instruction": "사용자 선호를 설명 관점으로만 사용하고 점수나 경로 좌표를 바꾸지 않는다.",
    }


def build_route_evidence_context(request: AiRoutePlanRequest) -> dict:
    graphhopper_sources = [
        badge.source
        for badge in request.evidenceBadges
        if badge.source.startswith("graphhopper.")
    ]
    return {
        "provider": "GraphHopper",
        "graphhopperSources": graphhopper_sources,
        "sceneryEvidenceStatus": request.sceneryEvidenceStatus,
        "evidenceBadges": [badge.model_dump() for badge in request.evidenceBadges],
        "instruction": "GraphHopper evidence는 도로/노면/자전거 네트워크/고도 설명 근거로만 사용한다.",
    }


def build_elevation_context(request: AiRoutePlanRequest) -> dict:
    return {
        "elevationPreference": request.elevationPreference,
        "elevationStatus": request.elevationStatus,
        "elevationSummary": request.elevationSummary.model_dump() if request.elevationSummary else None,
        "instruction": "평지/업힐/균형 선호는 backend score와 고도 evidence를 설명하는 데만 사용한다.",
    }


def build_canonical_route_context(request: AiRoutePlanRequest) -> dict:
    canonical_badges = [
        badge.model_dump()
        for badge in request.evidenceBadges
        if badge.source == "canonical-route"
    ]
    return {
        "textIntent": request.textIntent,
        "canonicalBadges": canonical_badges,
        "instruction": "정석 루트 근거가 있으면 왜 이 접근이 선택됐는지 짧게 설명하되 좌표를 새로 만들지 않는다.",
    }


def build_risk_policy_context(request: AiRoutePlanRequest) -> dict:
    must_mention = [
        badge.label
        for badge in request.evidenceBadges
        if badge.status in {"UNKNOWN", "FAILED", "WARNING"}
    ]
    return {
        "mustMention": must_mention,
        "forbiddenClaims": list(FORBIDDEN_CLAIMS),
        "instruction": "UNKNOWN, FAILED, WARNING evidence는 안전하다고 단정하지 말고 현장 확인 필요로 표현한다.",
    }


def build_copy_tone_context() -> dict:
    return {
        "tone": "자전거 여행 큐레이터",
        "style": "짧고 구체적이며 과장하지 않는 한국어",
        "avoid": ["운동 성과 코칭", "마케팅 과장", "확정되지 않은 안전 단정"],
    }


def build_output_schema_context() -> dict:
    return {
        "schema": {
            "headline": "짧은 추천 제목",
            "reason": "점수와 선호 근거 요약",
            "caution": "provider evidence 한계를 포함한 주의 문구",
            "nextAction": "사용자 CTA",
        },
        "immutableBackendFields": [
            "recommendationScore",
            "scoreBreakdown",
            "evidenceBadges",
            "routePoints",
            "elevationSummary",
        ],
        "instruction": "JSON object만 반환하고 backend immutable field를 재작성하지 않는다.",
    }


class GeminiExplanationClient:
    def __init__(self, api_key: str, model: str, timeout_sec: float = 4.5) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_sec = timeout_sec

    def compose(self, request: AiRoutePlanRequest, fallback: AiRouteExplanation) -> AiRouteExplanation:
        payload = self._build_payload(request, fallback)
        response = self._post_json(payload)
        text = self._extract_text(response)
        explanation = AiRouteExplanation(**extract_json_object(text))
        return sanitize_explanation(explanation, fallback)

    def _build_payload(self, request: AiRoutePlanRequest, fallback: AiRouteExplanation) -> dict:
        prompt = {
            "task": "자전거 여행 경로 추천 설명을 한국어 JSON으로 작성한다.",
            "hard_rules": [
                "JSON object만 반환한다.",
                "backend recommendationScore, scoreBreakdown, evidenceBadges를 바꾸지 않는다.",
                "공사/통제/노면 evidence가 UNKNOWN 또는 FAILED면 사실을 확정하지 않는다.",
                "안전 보장, 위험 없음, 공사 없음, 통제 없음 같은 단정 문구를 쓰지 않는다.",
                "운동 성과보다 자전거 여행 큐레이터 톤으로 쓴다.",
            ],
            "preferenceContext": build_preference_context(request),
            "routeEvidenceContext": build_route_evidence_context(request),
            "elevationContext": build_elevation_context(request),
            "canonicalRouteContext": build_canonical_route_context(request),
            "riskPolicyContext": build_risk_policy_context(request),
            "copyToneContext": build_copy_tone_context(),
            "outputSchemaContext": build_output_schema_context(),
            "route": {
                "destinationLabel": request.destinationLabel,
                "rideStyle": request.rideStyle,
                "elevationPreference": request.elevationPreference,
                "textIntent": request.textIntent,
                "preferenceSummary": request.preferenceSummary,
                "elevationStatus": request.elevationStatus,
                "sceneryEvidenceStatus": request.sceneryEvidenceStatus,
                "recommendationScore": request.recommendationScore,
                "scoreBreakdown": request.scoreBreakdown.model_dump() if request.scoreBreakdown else None,
                "elevationSummary": request.elevationSummary.model_dump() if request.elevationSummary else None,
                "weather": request.weather,
                "constructionSummary": request.constructionSummary,
                "roadSurfaceSummary": request.roadSurfaceSummary,
            },
            "fallback": fallback.model_dump(),
        }
        return {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": json.dumps(prompt, ensure_ascii=False)}],
                }
            ],
            "generationConfig": {
                "temperature": 0.4,
                "maxOutputTokens": 1024,
                "responseMimeType": "application/json",
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }

    def _post_json(self, payload: dict) -> dict:
        model = urllib.parse.quote(self.model, safe="")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "x-goog-api-key": self.api_key,
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
            return json.loads(response.read().decode("utf-8"))

    def _extract_text(self, response: dict) -> str:
        candidates = response.get("candidates") or []
        if not candidates:
            raise ValueError("Gemini 응답에 candidates가 없습니다.")
        parts = candidates[0].get("content", {}).get("parts") or []
        texts = [part.get("text", "") for part in parts if part.get("text")]
        if not texts:
            raise ValueError("Gemini 응답에 text part가 없습니다.")
        return "\n".join(texts)


def extract_json_object(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end < start:
            raise ValueError("JSON object를 찾을 수 없습니다.")
        cleaned = cleaned[start : end + 1]
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("Gemini explanation은 JSON object여야 합니다.")
    return parsed


def sanitize_explanation(explanation: AiRouteExplanation, fallback: AiRouteExplanation) -> AiRouteExplanation:
    values = [
        explanation.headline,
        explanation.reason,
        explanation.caution,
        explanation.nextAction,
    ]
    if any(not value or not value.strip() for value in values):
        return fallback
    joined = " ".join(values)
    if any(claim in joined for claim in FORBIDDEN_CLAIMS):
        return fallback
    return explanation


def compose_with_llm(
    request: AiRoutePlanRequest,
    fallback: AiRouteExplanation,
    *,
    api_key: str | None,
    model: str,
) -> AiRouteExplanation:
    if not api_key:
        return fallback
    try:
        return GeminiExplanationClient(api_key=api_key, model=model).compose(request, fallback)
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
        return fallback
