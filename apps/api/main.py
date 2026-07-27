from fastapi import FastAPI
from apps.api.routes import router
from apps.api.websocket import websocket_router

app = FastAPI(title="FinSight API", version="0.1.0")
app.include_router(router, prefix="/api/v1")
app.include_router(websocket_router)
