from fastapi import FastAPI

from apps.api.middleware import TenantAuthMiddleware
from apps.api.routes import compute_router, router

app = FastAPI(title="FinSight API", version="0.1.0")
app.add_middleware(TenantAuthMiddleware)
app.include_router(router, prefix="/api/v1")
app.include_router(compute_router)
