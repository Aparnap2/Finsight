from fastapi import FastAPI
from backend.api.routes import router
from backend.api.websocket import websocket_router

app = FastAPI(title="FinSight API", version="0.1.0")
app.include_router(router, prefix="/api/v1")
app.include_router(websocket_router)
