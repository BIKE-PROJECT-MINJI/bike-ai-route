from __future__ import annotations

import uuid
from typing import TypedDict

from langgraph.graph import END, StateGraph

from .llm import compose_with_llm
from .schemas import (
    AiRouteEvidenceBadge,
    AiRouteExplanation,
    AiRoutePlanRequest,
    AiRoutePlanResponse,
    AiRoutePoint,
    AiRouteRisk,
    RecommendationScore,
    AiRouteElevationSummary,
)
from .settings import WorkerSettings


class RouteGraphState(TypedDict, total=False):
    request: AiRoutePlanRequest
    risks: list[AiRouteRisk]
    route_points: list[AiRoutePoint]
    summary: str
    actions: list[str]
    explanation: AiRouteExplanation


def collect_context(state: RouteGraphState) -> RouteGraphState:
    request = state["request"]
    risks: list[AiRouteRisk] = []
    if request.constructionSummary:
        risks.append(
            AiRouteRisk(
                type="construction",
                label="공사 정보",
                severity="unknown",
                summary=request.constructionSummary,
            )
        )
    if request.roadSurfaceSummary:
        risks.append(
            AiRouteRisk(
                type="surface",
                label="노면 정보",
                severity="unknown",
                summary=request.roadSurfaceSummary,
            )
        )
    return {**state, "risks": risks}


def select_route(state: RouteGraphState) -> RouteGraphState:
    request = state["request"]
    if request.fallbackPlan is not None and request.fallbackPlan.routePoints:
        return {**state, "route_points": request.fallbackPlan.routePoints}
    destination_lat = request.destinationLat if request.destinationLat is not None else request.lat + 0.012
    destination_lon = request.destinationLon if request.destinationLon is not None else request.lon + 0.014
    mid_lat = (request.lat + destination_lat) / 2 + 0.004
    mid_lon = (request.lon + destination_lon) / 2
    return {
        **state,
        "route_points": [
            AiRoutePoint(lat=request.lat, lon=request.lon, label="현재 위치"),
            AiRoutePoint(lat=mid_lat, lon=mid_lon, label="조건 회피 구간"),
            AiRoutePoint(lat=destination_lat, lon=destination_lon, label=request.destinationLabel or "추천 도착지"),
        ],
    }


def summarize(state: RouteGraphState) -> RouteGraphState:
    request = state["request"]
    destination = request.destinationLabel or "추천 도착지"
    score = score_breakdown(request)
    settings = WorkerSettings.from_env()
    fallback_explanation = AiRouteExplanation(
        headline=f"{destination}까지 {ride_style_label(request.rideStyle)} 자전거 여행길을 골랐어요.",
        reason=f"추천점수 {score.total}점, 경치 {score.scenery}점, 자전거도로 {score.bikePath}점 기준입니다.",
        caution=build_caution(request.evidenceBadges),
        nextAction=next_action(settings),
    )
    return {
        **state,
        "summary": f"{destination}까지 날씨, 공사, 노면 조건을 보수적으로 반영한 경로입니다.",
        "actions": [
            "출발 전 현장 표지와 자전거 통행 가능 여부를 확인하세요.",
            "공사/노면 provider evidence가 없으면 위험도는 미확인으로 유지하세요.",
        ],
        "explanation": compose_with_llm(
            request,
            fallback_explanation,
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
        ),
    }


def build_graph():
    graph = StateGraph(RouteGraphState)
    graph.add_node("collect_context", collect_context)
    graph.add_node("select_route", select_route)
    graph.add_node("summarize", summarize)
    graph.set_entry_point("collect_context")
    graph.add_edge("collect_context", "select_route")
    graph.add_edge("select_route", "summarize")
    graph.add_edge("summarize", END)
    return graph.compile()


ROUTE_GRAPH = build_graph()


def plan_route(request: AiRoutePlanRequest) -> AiRoutePlanResponse:
    result = ROUTE_GRAPH.invoke({"request": request})
    score = score_breakdown(request)
    return AiRoutePlanResponse(
        planId=f"ai-route-{uuid.uuid4()}",
        summary=result["summary"],
        confidence="medium",
        weather=request.weather.get("weather") if request.weather else None,
        wind=request.weather.get("wind") if request.weather else None,
        routePoints=result["route_points"],
        risks=result["risks"],
        actions=result["actions"],
        recommendationScore=request.recommendationScore if request.recommendationScore is not None else score.total,
        scoreBreakdown=score,
        explanation=result["explanation"],
        evidenceBadges=request.evidenceBadges,
        elevationSummary=request.elevationSummary,
        preferenceSummary=request.preferenceSummary,
        elevationStatus=request.elevationStatus,
        sceneryEvidenceStatus=request.sceneryEvidenceStatus,
    )


def score_breakdown(request: AiRoutePlanRequest) -> RecommendationScore:
    if request.scoreBreakdown is not None:
        return request.scoreBreakdown
    return RecommendationScore(
        total=request.recommendationScore or 70,
        scenery=70,
        bikePath=70,
        safety=70,
        condition=70,
        preferenceFit=70,
        distancePenalty=0,
        unknownPenalty=count_evidence(request.evidenceBadges, "UNKNOWN"),
    )


def ride_style_label(ride_style: str | None) -> str:
    if ride_style == "SCENERY_FIRST":
        return "경치 우선"
    if ride_style == "BIKE_PATH_FIRST":
        return "자전거도로 우선"
    return "균형형"


def build_caution(evidence_badges: list[AiRouteEvidenceBadge]) -> str:
    unknown_labels = labels_by_status(evidence_badges, "UNKNOWN")
    failed_labels = labels_by_status(evidence_badges, "FAILED")
    warning_labels = labels_by_status(evidence_badges, "WARNING")
    parts: list[str] = []
    if warning_labels:
        parts.append(f"{', '.join(warning_labels)} 주의 조건이 있습니다")
    if unknown_labels:
        parts.append(f"{', '.join(unknown_labels)} 정보는 아직 확인되지 않았습니다")
    if failed_labels:
        parts.append(f"{', '.join(failed_labels)} provider 확인 실패가 있습니다")
    if parts:
        return "; ".join(parts) + ". 출발 전 현장 표지를 확인하세요."
    return "현재 provider evidence 기준으로 큰 주의 항목은 없습니다."


def labels_by_status(evidence_badges: list[AiRouteEvidenceBadge], status: str) -> list[str]:
    return [badge.label for badge in evidence_badges if badge.status == status]


def count_evidence(evidence_badges: list[AiRouteEvidenceBadge], status: str) -> int:
    return sum(1 for badge in evidence_badges if badge.status == status)


def next_action(settings: WorkerSettings) -> str:
    if settings.llm_enabled():
        return "이 경로로 출발"
    return "이 경로로 출발"
