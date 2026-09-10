"""WebSocket routes for real-time streaming updates."""

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.streaming.schemas import WebSocketEnvelope, WebSocketMessageType
from app.streaming.state import train_state_updater
from app.streaming.websocket import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websockets"])


@router.websocket("/ws/trains/{train_number}")
async def websocket_train_stream(websocket: WebSocket, train_number: str) -> None:
    """Stream real-time position and ETA predictions for a specific train."""
    topic = f"train:{train_number}"
    await ws_manager.connect(websocket, [topic])

    # Send current operational state if known
    try:
        current_state = await train_state_updater.get_active_state(train_number)
        if current_state:
            envelope = WebSocketEnvelope(
                topic=topic,
                event_type=WebSocketMessageType.TRAIN_STATE,
                data=current_state.model_dump(mode="json"),
            )
            await websocket.send_text(envelope.model_dump_json())

        while True:
            # Keep connection open, respond to ping/pong or client messages
            data = await websocket.receive_text()
            if data.strip().lower() == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception as exc:
        logger.debug("WebSocket train stream error for %s: %s", train_number, exc)
        await ws_manager.disconnect(websocket)


@router.websocket("/ws/stations/{station_code}")
async def websocket_station_stream(websocket: WebSocket, station_code: str) -> None:
    """Stream real-time arrivals and predictions for a specific station."""
    topic = f"station:{station_code.upper()}"
    await ws_manager.connect(websocket, [topic])

    try:
        while True:
            data = await websocket.receive_text()
            if data.strip().lower() == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception as exc:
        logger.debug("WebSocket station stream error for %s: %s", station_code, exc)
        await ws_manager.disconnect(websocket)


@router.websocket("/ws/network")
async def websocket_network_stream(websocket: WebSocket) -> None:
    """Stream network-level delay cascades, alerts, and congestion risks."""
    topic = "network"
    await ws_manager.connect(websocket, [topic])

    try:
        while True:
            data = await websocket.receive_text()
            if data.strip().lower() == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception as exc:
        logger.debug("WebSocket network stream error: %s", exc)
        await ws_manager.disconnect(websocket)


@router.websocket("/ws/updates")
async def websocket_all_updates_stream(websocket: WebSocket) -> None:
    """Stream all real-time events across the entire railway network."""
    topic = "all"
    await ws_manager.connect(websocket, [topic])

    try:
        while True:
            data = await websocket.receive_text()
            if data.strip().lower() == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception as exc:
        logger.debug("WebSocket all-updates stream error: %s", exc)
        await ws_manager.disconnect(websocket)
