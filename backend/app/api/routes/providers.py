from fastapi import APIRouter
from pydantic import BaseModel

from app.providers.manager import provider_manager
from app.providers.models import ProviderName, ProviderStatus

router = APIRouter(prefix="/providers", tags=["providers"])


class ProvidersStatusResponse(BaseModel):
    providers: list[ProviderStatus]


@router.get("/status", response_model=ProvidersStatusResponse, summary="Get the status of every configured data provider")
async def get_providers_status() -> ProvidersStatusResponse:
    return ProvidersStatusResponse(providers=await provider_manager.list_provider_statuses())


@router.get("/{provider}/status", response_model=ProviderStatus, summary="Get detailed health for one data provider")
async def get_provider_status(provider: ProviderName) -> ProviderStatus:
    # `provider` is validated against ProviderName by FastAPI before this runs (422 on
    # an unknown value), and every ProviderName has a registered adapter, so this is
    # always a hit — no not-found branch needed.
    return await provider_manager.get_provider_status(provider)
