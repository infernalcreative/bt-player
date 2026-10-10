# /opt/bt-player/endpoints/health.py
from fastapi import APIRouter, HTTPException, status
import asyncio

router = APIRouter(prefix="/status", tags=["Health"])

@router.post("/health")
async def health():
    return {"status": "ok", "plugin": "health", "message": "ok"}

