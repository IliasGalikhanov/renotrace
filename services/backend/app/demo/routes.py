from fastapi import APIRouter, Response

from .models import DemoResult, RecalculateRequest, ScenarioSummary
from .service import catalog, demo_result

router = APIRouter(prefix="/api/demo", tags=["Synthetic demo (no persistence)"])


@router.get("/scenarios", response_model=list[ScenarioSummary])
def scenarios(response: Response) -> list[ScenarioSummary]:
    """List server-owned synthetic examples. No private cases or visitor state."""
    response.headers["Cache-Control"] = "no-store"
    return [sample.summary for sample in catalog().samples]


@router.get(
    "/scenarios/{scenario_id}",
    response_model=DemoResult,
    responses={404: {"description": "Unknown scenario"}},
)
def scenario(scenario_id: str, response: Response) -> DemoResult:
    """Return source excerpts, immutable example history and its actual initial calculation."""
    response.headers["Cache-Control"] = "no-store"
    return demo_result(scenario_id, [])


@router.post(
    "/scenarios/{scenario_id}/calculate",
    response_model=DemoResult,
    responses={404: {"description": "Unknown scenario"}},
)
def recalculate(scenario_id: str, request: RecalculateRequest, response: Response) -> DemoResult:
    """Rebuild a fresh example and apply allowed actions, last answer per scope wins.

    No persistence, sessions, transactions, permanent cases or snapshots. Send the
    entire current action list on every request; an empty list resets the sample.
    Domain revision/uncertainty checks still apply. Arbitrary HistoryInput is not accepted.
    """
    response.headers["Cache-Control"] = "no-store"
    return demo_result(scenario_id, request.actions)
