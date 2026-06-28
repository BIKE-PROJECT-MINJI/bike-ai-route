# BIKE AI Route Worker

BIKE/GAJA의 AI 코스생성 설명 worker다.
이 저장소는 백엔드가 만든 route candidate, score breakdown, provider evidence를 받아 사용자에게 보여줄 설명과 주의 문구를 생성한다.

## 역할

이 worker는 route point의 source of truth가 아니다.

| 책임 | 담당 |
|---|---|
| 자연어를 라우팅 선호로 정규화 | 백엔드 parser/정책, 필요 시 AI 보조 |
| 실제 경로 탐색 | GraphHopper profile/custom model/weighting |
| 거리/시간/고도/노면/경사/자전거도로 evidence | GraphHopper route detail, 보조 GIS layer |
| 후보 점수화 | 백엔드 scorer |
| 후보 설명/trade-off/주의 문구 | 이 AI worker |

즉, 운영 방향은 `자연어 -> RoutePreference -> GraphHopper/GIS evidence -> backend scorer -> AI explanation`이다.
LLM이 좌표를 직접 만들거나 route point를 임의로 수정하지 않는다.

## 현재 기능

- FastAPI 기반 `/v1/ai-routes/plan` endpoint
- Gemini provider 우선
- provider key가 없거나 실패하면 deterministic fallback explanation 생성
- 백엔드가 전달한 `recommendationScore`, `scoreBreakdown`, `evidenceBadges`, `fallbackPlan`을 보존
- provider evidence에 없는 공사/통제/노면 사실을 생성하지 않도록 제한

## 입력/출력 원칙

입력:

- 현재 위치
- 목적지 후보
- 백엔드 추천 점수
- score breakdown
- provider evidence badge
- fallback plan

출력:

- 후보 요약
- 추천 이유
- trade-off
- caution
- provider/fallback metadata를 해치지 않는 설명

## 로컬 실행

```bash
uv sync
GEMINI_API_KEY=... uv run uvicorn app.main:app --reload --port 8091
```

백엔드 연결:

```bash
cd ../bike-back
AI_ROUTE_WORKER_BASE_URL=http://localhost:8091 ./gradlew bootRun
```

## 테스트

```bash
uv sync
uv run pytest
```

## 환경 변수

| 변수 | 설명 |
|---|---|
| `GEMINI_API_KEY` 또는 `GOOGLE_API_KEY` | Google AI Studio/Gemini 호출 키. 로그/문서/앱에 평문 저장 금지 |
| `GEMINI_MODEL` 또는 `GOOGLE_MODEL` | Gemini 모델명. 기본값 `gemini-2.5-flash` |
| `OPENAI_API_KEY` | 과거 호환용. 현재 1차 LLM provider는 Gemini |

## 운영 제약

- AI worker는 route point를 만들지 않는다.
- GraphHopper/GIS evidence가 없는 내용을 사실처럼 말하지 않는다.
- provider 실패는 fallback explanation으로 격리한다.
- high load 테스트에서는 실제 LLM provider를 무차별 호출하지 않는다.
- 고부하는 fake/self-host 중심으로 보고, 실제 provider는 low VU drill로 연결성과 latency를 확인한다.

## 백엔드와의 관계

백엔드 저장소: `BIKE-PROJECT-MINJI/bike-back`

백엔드는 `AI_ROUTE_WORKER_BASE_URL`이 없으면 deterministic fallback client로 동작한다.
이 worker가 있으면 백엔드는 HTTP client로 worker를 호출해 설명 후보를 받는다.

## 고도화 예정

- 자연어 선호를 `RoutePreference`로 더 정교하게 정규화
- `FLAT_FIRST`, `RIVERSIDE`, `BIKE_PATH_FIRST`, `LOW_TRAFFIC`, `LOOP` 같은 선호 유형별 설명 품질 강화
- GraphHopper custom model/weighting 결과와 score breakdown을 사용자 문장으로 더 정확히 설명
- `elevationStatus=UNAVAILABLE`, `sceneryEvidenceStatus=PARTIAL/UNKNOWN` 같은 품질 metadata를 설명에 반영
- 수변/공원/POI GIS layer가 붙으면 scenery evidence를 더 보수적으로 설명

## 보안

- `.env`와 provider key는 커밋하지 않는다.
- k6 summary, pytest log, app log에 provider key, token, raw 위치 trace를 남기지 않는다.
- 포트폴리오나 README에는 실제 key, URL credential, 개인 위치 데이터를 쓰지 않는다.
