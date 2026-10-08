from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from apps.api.approvals import router as approvals_router
from apps.api.approvals import validation_error_handler
from apps.api.execution_routes import router as execution_router
from apps.api.middleware import TenantAuthMiddleware
from apps.api.observability import RequestIDMiddleware, create_readiness_router
from apps.api.observations import router as observations_router
from apps.api.routes import compute_router, router
from apps.api.webhooks import router as webhook_router

app = FastAPI(title="FinSight API", version="0.1.0")
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(TenantAuthMiddleware)
app.include_router(create_readiness_router())
app.include_router(router, prefix="/api/v1")
app.include_router(compute_router)
app.include_router(webhook_router)
app.include_router(approvals_router)
app.include_router(execution_router)
app.include_router(observations_router)
