"""Tests for WebSocket connection manager, topic routing, and endpoints."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.streaming.schemas import (
    PredictionUpdatePayload,
    WebSocketEnvelope,
    WebSocketMessageType,
)
from app.streaming.websocket import WebSocketConnectionManager


@pytest.mark.asyncio
async def test_websocket_manager_topic_routing():
    manager = WebSocketConnectionManager()

    ws_train = AsyncMock()
    ws_station = AsyncMock()
    ws_all = AsyncMock()

    # Connect clients
    await manager.connect(ws_train, ["train:12002"])
    await manager.connect(ws_station, ["station:NDLS"])
    await manager.connect(ws_all, ["all"])

    assert manager.get_active_connection_count() == 3

    # Broadcast to train:12002
    envelope = WebSocketEnvelope(
        topic="train:12002",
        event_type=WebSocketMessageType.PREDICTION_UPDATE,
        data={"train_number": "12002", "delay": 5},
    )
    delivered = await manager.broadcast_to_topic("train:12002", envelope)
    # Delivered to ws_train and ws_all (wildcard)
    assert delivered == 2

    # Broadcast prediction payload
    pred = PredictionUpdatePayload(train_number="12002", station_code="NDLS")
    await manager.broadcast_prediction(pred)

    # Disconnect
    await manager.disconnect(ws_train)
    assert manager.get_active_connection_count() == 2
    await manager.disconnect(ws_station)
    await manager.disconnect(ws_all)
    assert manager.get_active_connection_count() == 0


def test_websocket_endpoint_connection():
    client = TestClient(app)
    with client.websocket_connect("/ws/trains/12002") as websocket:
        websocket.send_text("ping")
        data = websocket.receive_text()
        # The first message might be initial TRAIN_STATE if present, or "pong"
        if "train_state" in data:
            data = websocket.receive_text()
        assert data.lower() == "pong"
