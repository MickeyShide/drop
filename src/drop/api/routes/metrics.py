from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST

from drop.metrics import generate_metrics

router = APIRouter(tags=["metrics"])


@router.get(
    "/metrics",
    summary="Get Prometheus metrics",
    include_in_schema=False,
)
def get_metrics() -> Response:
    return Response(
        content=generate_metrics(),
        media_type=CONTENT_TYPE_LATEST,
    )
