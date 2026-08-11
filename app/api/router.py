from fastapi import APIRouter

from app.api import admin, ai, esg, festival, map, operations, public, survey, visitor

api_router = APIRouter()
api_router.include_router(public.router, prefix="/public", tags=["public"])
api_router.include_router(visitor.router, prefix="/visitor", tags=["visitor"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])

# Legacy MVP routes kept for local frontend compatibility during migration.
api_router.include_router(festival.router, prefix="/festival", tags=["festival"])
api_router.include_router(map.router, prefix="/map", tags=["map"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(operations.router, prefix="/operations", tags=["operations"])
api_router.include_router(esg.router, prefix="/esg", tags=["esg"])
api_router.include_router(survey.router, prefix="/survey", tags=["survey"])
