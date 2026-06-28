from app.graph import plan_route
from app.llm import (
    GeminiExplanationClient,
    build_canonical_route_context,
    build_copy_tone_context,
    build_elevation_context,
    build_output_schema_context,
    build_preference_context,
    build_risk_policy_context,
    build_route_evidence_context,
    extract_json_object,
    sanitize_explanation,
)
from app.schemas import (
    AiRouteEvidenceBadge,
    AiRouteElevationSummary,
    AiRouteExplanation,
    AiRoutePlanRequest,
    RecommendationScore,
)
from app.settings import WorkerSettings


def test_worker_composes_explanation_from_backend_score_and_evidence():
    request = AiRoutePlanRequest(
        lat=37.5665,
        lon=126.9780,
        destinationLat=37.5796,
        destinationLon=126.9770,
        destinationLabel="북악스카이웨이",
        rideStyle="SCENERY_FIRST",
        recommendationScore=82,
        scoreBreakdown=RecommendationScore(
            total=82,
            scenery=91,
            bikePath=78,
            safety=72,
            condition=68,
            preferenceFit=88,
            distancePenalty=4,
            unknownPenalty=12,
        ),
        evidenceBadges=[
            AiRouteEvidenceBadge(
                source="weather",
                label="날씨",
                status="VERIFIED",
                severity="INFO",
                summary="맑음, 북서풍 12km/h",
            ),
            AiRouteEvidenceBadge(
                source="roadwork",
                label="공사",
                status="UNKNOWN",
                severity="UNKNOWN",
                summary="공사 정보 미확인",
            ),
            AiRouteEvidenceBadge(
                source="surface",
                label="노면",
                status="FAILED",
                severity="UNKNOWN",
                summary="노면 provider 확인 실패",
            ),
        ],
    )

    response = plan_route(request)

    assert response.aiGenerated is True
    assert response.recommendationScore == 82
    assert response.scoreBreakdown.total == 82
    assert response.explanation == AiRouteExplanation(
        headline="북악스카이웨이까지 경치 우선 자전거 여행길을 골랐어요.",
        reason="추천점수 82점, 경치 91점, 자전거도로 78점 기준입니다.",
        caution="공사 정보는 아직 확인되지 않았습니다; 노면 provider 확인 실패가 있습니다. 출발 전 현장 표지를 확인하세요.",
        nextAction="이 경로로 출발",
    )
    assert [badge.status for badge in response.evidenceBadges] == ["VERIFIED", "UNKNOWN", "FAILED"]
    assert "공사 없음" not in response.explanation.caution
    assert "안전 보장" not in response.explanation.caution


def test_worker_preserves_backend_fallback_route_points():
    request = AiRoutePlanRequest(
        lat=37.4812,
        lon=126.9527,
        destinationLat=37.5404,
        destinationLon=127.0692,
        destinationLabel="건대입구",
        rideStyle="BIKE_PATH_FIRST",
        recommendationScore=84,
        fallbackPlan={
            "routePoints": [
                {"lat": 37.4812, "lon": 126.9527, "label": "GraphHopper"},
                {"lat": 37.5000, "lon": 127.0000, "label": "GraphHopper"},
                {"lat": 37.5200, "lon": 127.0400, "label": "GraphHopper"},
                {"lat": 37.5404, "lon": 127.0692, "label": "GraphHopper"},
            ]
        },
    )

    response = plan_route(request)

    assert len(response.routePoints) == 4
    assert [point.label for point in response.routePoints] == ["GraphHopper"] * 4


def test_worker_preserves_backend_elevation_summary():
    request = AiRoutePlanRequest(
        lat=37.4812,
        lon=126.9527,
        destinationLat=37.5512,
        destinationLon=126.9882,
        destinationLabel="남산 N서울타워",
        rideStyle="SCENERY_FIRST",
        elevationPreference="CLIMB_FIRST",
        recommendationScore=78,
        elevationSummary=AiRouteElevationSummary(
            totalAscentM=132.0,
            totalDescentM=28.0,
            minAltitudeM=35.0,
            maxAltitudeM=236.0,
            maxSlopePercent=12.5,
            averageSlopePercent=4.2,
        ),
        fallbackPlan={
            "routePoints": [
                {"lat": 37.4812, "lon": 126.9527, "label": "GraphHopper", "altitudeM": 42.0},
                {"lat": 37.5512, "lon": 126.9882, "label": "GraphHopper", "altitudeM": 236.0},
            ]
        },
    )

    response = plan_route(request)

    assert response.elevationSummary is not None
    assert response.elevationSummary.totalAscentM == 132.0
    assert response.routePoints[1].altitudeM == 236.0


def test_worker_preserves_backend_preference_and_evidence_status():
    request = AiRoutePlanRequest(
        lat=37.4812,
        lon=126.9527,
        destinationLat=37.5512,
        destinationLon=126.9882,
        destinationLabel="남산 N서울타워",
        rideStyle="SCENERY_FIRST",
        elevationPreference="CLIMB_FIRST",
        preferenceSummary="경치 우선 + 업힐 선호 + 남산 정석 접근",
        elevationStatus="VERIFIED",
        sceneryEvidenceStatus="PARTIAL",
        recommendationScore=82,
    )

    response = plan_route(request)

    assert response.preferenceSummary == "경치 우선 + 업힐 선호 + 남산 정석 접근"
    assert response.elevationStatus == "VERIFIED"
    assert response.sceneryEvidenceStatus == "PARTIAL"


def test_settings_prefers_gemini_key_without_exposing_secret(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")

    settings = WorkerSettings.from_env()

    assert settings.llm_enabled() is True
    assert settings.llm_provider == "gemini"
    assert settings.gemini_model == "gemini-2.5-flash"


def test_gemini_client_builds_safe_json_explanation_from_response(monkeypatch):
    request = AiRoutePlanRequest(
        lat=37.5665,
        lon=126.9780,
        destinationLabel="여의도 한강공원",
        recommendationScore=63,
        scoreBreakdown=RecommendationScore(
            total=63,
            scenery=70,
            bikePath=70,
            safety=72,
            condition=72,
            preferenceFit=75,
            distancePenalty=0,
            unknownPenalty=8,
        ),
        evidenceBadges=[
            AiRouteEvidenceBadge(
                source="weather",
                label="날씨",
                status="VERIFIED",
                severity="INFO",
                summary="흐림, 북동풍 3km/h",
            ),
            AiRouteEvidenceBadge(
                source="construction",
                label="공사",
                status="UNKNOWN",
                severity="UNKNOWN",
                summary="공사 provider 미연결",
            ),
        ],
    )
    fallback = AiRouteExplanation(
        headline="여의도 한강공원까지 자전거 여행길을 선별했어요.",
        reason="경치 70, 자전거도로 70, 선호도 75 기준으로 골랐어요.",
        caution="공사 정보는 아직 확인되지 않았습니다. 출발 전 현장 표지를 확인하세요.",
        nextAction="이 경로로 출발",
    )

    def fake_post_json(self, payload):
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": (
                                    '{"headline":"한강 쪽 풍경을 살린 코스를 골랐어요.",'
                                    '"reason":"추천점수와 자전거도로 점수를 기준으로 설명했습니다.",'
                                    '"caution":"공사 정보는 확인되지 않았으니 현장 표지를 확인하세요.",'
                                    '"nextAction":"이 경로로 출발"}'
                                )
                            }
                        ]
                    }
                }
            ]
        }

    monkeypatch.setattr(GeminiExplanationClient, "_post_json", fake_post_json)

    client = GeminiExplanationClient(api_key="test-gemini-key", model="gemini-2.5-flash")
    explanation = client.compose(request, fallback)

    assert explanation.headline == "한강 쪽 풍경을 살린 코스를 골랐어요."
    assert "공사 없음" not in explanation.caution
    assert "안전 보장" not in explanation.caution


def test_gemini_client_reserves_output_budget_for_json_explanation():
    request = AiRoutePlanRequest(
        lat=37.481247,
        lon=126.952739,
        destinationLabel="부천역",
        recommendationScore=59,
    )
    fallback = AiRouteExplanation(
        headline="기본 제목",
        reason="기본 사유",
        caution="기본 주의",
        nextAction="이 경로로 출발",
    )

    payload = GeminiExplanationClient(
        api_key="test-gemini-key",
        model="gemini-2.5-flash",
    )._build_payload(request, fallback)

    generation_config = payload["generationConfig"]
    assert generation_config["maxOutputTokens"] >= 1024
    assert generation_config["thinkingConfig"] == {"thinkingBudget": 0}


def test_gemini_prompt_uses_domain_prompt_sections():
    request = AiRoutePlanRequest(
        lat=37.481247,
        lon=126.952739,
        destinationLabel="부천역",
        rideStyle="SCENERY_FIRST",
        elevationPreference="CLIMB_FIRST",
        textIntent="CANONICAL_NAMSAN_NATIONAL_THEATER",
        recommendationScore=59,
        scoreBreakdown=RecommendationScore(
            total=59,
            scenery=78,
            bikePath=100,
            safety=70,
            condition=67,
            elevation=91,
            preferenceFit=80,
            distancePenalty=20,
            unknownPenalty=2,
        ),
        elevationSummary={
            "totalAscentM": 132.0,
            "totalDescentM": 28.0,
            "minAltitudeM": 35.0,
            "maxAltitudeM": 236.0,
            "maxSlopePercent": 12.5,
            "averageSlopePercent": 4.2,
        },
        evidenceBadges=[
            AiRouteEvidenceBadge(
                source="graphhopper.road_environment",
                label="도로 환경",
                status="WARNING",
                severity="MEDIUM",
                summary="교량/터널 구간 주의",
            ),
            AiRouteEvidenceBadge(
                source="canonical-route",
                label="남산 정석 루트",
                status="VERIFIED",
                severity="INFO",
                summary="국립극장 접근",
            ),
            AiRouteEvidenceBadge(
                source="surface",
                label="노면",
                status="UNKNOWN",
                severity="UNKNOWN",
                summary="노면 정보 미확인",
            ),
        ],
    )
    fallback = AiRouteExplanation(
        headline="기본 제목",
        reason="기본 사유",
        caution="기본 주의",
        nextAction="이 경로로 출발",
    )

    payload = GeminiExplanationClient(
        api_key="test-gemini-key",
        model="gemini-2.5-flash",
    )._build_payload(request, fallback)
    text = payload["contents"][0]["parts"][0]["text"]

    assert '"preferenceContext"' in text
    assert '"routeEvidenceContext"' in text
    assert '"elevationContext"' in text
    assert '"canonicalRouteContext"' in text
    assert '"riskPolicyContext"' in text
    assert '"copyToneContext"' in text
    assert '"outputSchemaContext"' in text
    assert "GraphHopper" in text
    assert "CLIMB_FIRST" in text
    assert "국립극장" in text
    assert "안전 보장" in text


def test_domain_prompt_sections_are_testable_units():
    request = AiRoutePlanRequest(
        lat=37.481247,
        lon=126.952739,
        destinationLabel="부천역",
        rideStyle="BIKE_PATH_FIRST",
        evidenceBadges=[
            AiRouteEvidenceBadge(
                source="graphhopper.bike_network",
                label="자전거 네트워크",
                status="OK",
                severity="LOW",
                summary="자전거 네트워크 detail 반영",
            ),
            AiRouteEvidenceBadge(
                source="construction",
                label="공사",
                status="FAILED",
                severity="UNKNOWN",
                summary="공사 provider 확인 실패",
            ),
        ],
    )

    assert build_preference_context(request)["primaryLens"] == "자전거도로 우선"
    assert build_preference_context(request)["preferenceSummary"] is None
    assert build_route_evidence_context(request)["graphhopperSources"] == ["graphhopper.bike_network"]
    assert "공사" in build_risk_policy_context(request)["mustMention"]
    assert build_copy_tone_context()["tone"] == "자전거 여행 큐레이터"
    assert build_elevation_context(request)["elevationSummary"] is None
    assert build_canonical_route_context(request)["canonicalBadges"] == []
    assert build_output_schema_context()["immutableBackendFields"] == [
        "recommendationScore",
        "scoreBreakdown",
        "evidenceBadges",
        "routePoints",
        "elevationSummary",
    ]


def test_sanitize_explanation_rejects_unsupported_safety_claims():
    fallback = AiRouteExplanation(
        headline="기본 설명",
        reason="기본 사유",
        caution="공사 정보는 확인되지 않았습니다.",
        nextAction="이 경로로 출발",
    )

    unsafe = AiRouteExplanation(
        headline="안전 보장 경로입니다.",
        reason="공사 없음 기준입니다.",
        caution="위험 없음",
        nextAction="출발",
    )

    assert sanitize_explanation(unsafe, fallback) == fallback


def test_extract_json_object_accepts_markdown_fenced_json():
    text = """```json
    {"headline":"h","reason":"r","caution":"c","nextAction":"n"}
    ```"""

    assert extract_json_object(text)["headline"] == "h"
