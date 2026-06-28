from fastapi import FastAPI

from .graph import plan_route
from .schemas import AiRoutePlanRequest, AiRoutePlanResponse

app = FastAPI(title="BIKE AI Route Worker")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "bike-ai-route"}


@app.post("/v1/ai-routes/plan", response_model=AiRoutePlanResponse)
def plan(request: AiRoutePlanRequest) -> AiRoutePlanResponse:
    return plan_route(request)

