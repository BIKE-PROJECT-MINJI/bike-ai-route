from pydantic import BaseModel, Field


class AiRoutePoint(BaseModel):
    lat: float
    lon: float
    label: str
    altitudeM: float | None = None


class AiRouteRisk(BaseModel):
    type: str
    label: str
    severity: str
    summary: str


class RecommendationScore(BaseModel):
    total: int
    scenery: int
    bikePath: int
    safety: int
    condition: int
    elevation: int | None = None
    preferenceFit: int
    distancePenalty: int
    unknownPenalty: int


class AiRouteElevationSummary(BaseModel):
    totalAscentM: float | None = None
    totalDescentM: float | None = None
    minAltitudeM: float | None = None
    maxAltitudeM: float | None = None
    maxSlopePercent: float | None = None
    averageSlopePercent: float | None = None


class AiRouteEvidenceBadge(BaseModel):
    source: str
    label: str
    status: str
    severity: str
    summary: str
    observedAt: str | None = None


class AiRouteExplanation(BaseModel):
    headline: str
    reason: str
    caution: str
    nextAction: str


class AiRouteFallbackPlan(BaseModel):
    routePoints: list[AiRoutePoint] = Field(default_factory=list)


class AiRoutePlanRequest(BaseModel):
    lat: float
    lon: float
    destinationLat: float | None = None
    destinationLon: float | None = None
    destinationLabel: str | None = None
    rideStyle: str | None = "balanced"
    elevationPreference: str | None = None
    textIntent: str | None = None
    weather: dict | None = None
    constructionSummary: str | None = None
    roadSurfaceSummary: str | None = None
    recommendationScore: int | None = None
    scoreBreakdown: RecommendationScore | None = None
    elevationSummary: AiRouteElevationSummary | None = None
    evidenceBadges: list[AiRouteEvidenceBadge] = Field(default_factory=list)
    fallbackPlan: AiRouteFallbackPlan | None = None


class AiRoutePlanResponse(BaseModel):
    planId: str
    status: str = "READY"
    summary: str
    confidence: str
    weather: dict | None = None
    wind: dict | None = None
    routePoints: list[AiRoutePoint] = Field(default_factory=list)
    risks: list[AiRouteRisk] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    recommendationScore: int
    scoreBreakdown: RecommendationScore
    explanation: AiRouteExplanation
    evidenceBadges: list[AiRouteEvidenceBadge] = Field(default_factory=list)
    aiGenerated: bool = True
    elevationSummary: AiRouteElevationSummary | None = None
