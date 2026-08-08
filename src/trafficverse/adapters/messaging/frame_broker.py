"""Bounded latest-state WebSocket broker implementing frame publishing hooks."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import JsonValue, TypeAdapter

from trafficverse.domain.models import SimulationFrame, WebSocketEnvelope

_JSON: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)
_TYPE_TOPIC = {
    "vehicle.delta": "vehicles",
    "traffic_light.delta": "traffic_lights",
    "component.health": "health",
    "event.created": "events",
}
_LATEST_ORDER = (
    "world.snapshot",
    "component.health",
    "vehicle.delta",
    "traffic_light.delta",
)
_CRITICAL_TYPES = {
    "command.accepted",
    "command.rejected",
    "experiment.state.changed",
    "event.created",
    "error",
    "session.ready",
}


def make_envelope(
    message_type: str,
    experiment_id: UUID,
    *,
    simulation_time_ms: int,
    sequence: int,
    payload: object,
    correlation_id: str | None = None,
) -> WebSocketEnvelope:
    return WebSocketEnvelope(
        type=message_type,
        message_id=str(uuid4()),
        correlation_id=correlation_id,
        experiment_id=experiment_id,
        simulation_time_ms=simulation_time_ms,
        sequence=sequence,
        sent_at=datetime.now(timezone.utc),
        payload=_JSON.validate_python(payload),
    )


class ClientMessageBuffer:
    def __init__(self, *, critical_capacity: int = 64) -> None:
        if critical_capacity <= 0:
            raise ValueError("critical message capacity must be positive")
        self._critical: deque[WebSocketEnvelope] = deque()
        self._critical_capacity = critical_capacity
        self._latest: dict[str, WebSocketEnvelope] = {}
        self._vehicle_states: dict[str, JsonValue] = {}
        self._collision_vehicle_ids: tuple[str, ...] = ()
        self._event = asyncio.Event()
        self._closed = False
        self._overflowed = False
        self.coalesced_vehicle_deltas = 0

    @property
    def depth(self) -> int:
        return len(self._critical) + len(self._latest)

    @property
    def overflowed(self) -> bool:
        return self._overflowed

    def offer(self, message: WebSocketEnvelope) -> None:
        if self._closed:
            return
        if message.type in _CRITICAL_TYPES:
            if len(self._critical) >= self._critical_capacity:
                self._overflowed = True
                self._closed = True
            else:
                self._critical.append(message)
            self._event.set()
            return
        if message.type == "vehicle.delta":
            if message.type in self._latest:
                self.coalesced_vehicle_deltas += 1
            payload = message.payload
            if isinstance(payload, dict):
                vehicles = payload.get("vehicles", [])
                if isinstance(vehicles, list):
                    for vehicle in vehicles:
                        if isinstance(vehicle, dict):
                            vehicle_id = vehicle.get("vehicle_id")
                            if isinstance(vehicle_id, str):
                                self._vehicle_states[vehicle_id] = vehicle
                collision_vehicle_ids = payload.get("collision_vehicle_ids", [])
                if isinstance(collision_vehicle_ids, list):
                    self._collision_vehicle_ids = tuple(
                        value for value in collision_vehicle_ids if isinstance(value, str)
                    )
            message = message.model_copy(
                update={
                    "payload": {
                        "vehicles": [
                            self._vehicle_states[key] for key in sorted(self._vehicle_states)
                        ],
                        "collision_vehicle_ids": list(self._collision_vehicle_ids),
                    }
                }
            )
        self._latest[message.type] = message
        self._event.set()

    async def next(self) -> WebSocketEnvelope:
        while True:
            if self._critical:
                return self._critical.popleft()
            for message_type in _LATEST_ORDER:
                message = self._latest.pop(message_type, None)
                if message is not None:
                    if message_type == "vehicle.delta":
                        self._vehicle_states.clear()
                    return message
            if self._closed:
                raise EOFError("client message buffer is closed")
            self._event.clear()
            await self._event.wait()

    def close(self) -> None:
        self._closed = True
        self._event.set()


class Subscription:
    def __init__(
        self,
        broker: FrameBroker,
        experiment_id: UUID,
        *,
        critical_capacity: int,
    ) -> None:
        self._broker = broker
        self.experiment_id = experiment_id
        self.topics: frozenset[str] = frozenset()
        self.max_hz = 10.0
        self.buffer = ClientMessageBuffer(critical_capacity=critical_capacity)

    def set_topics(self, topics: frozenset[str], *, max_hz: float) -> None:
        self._broker.set_topics(self, topics, max_hz=max_hz)

    def offer(self, message: WebSocketEnvelope) -> None:
        topic = _TYPE_TOPIC.get(message.type)
        if topic is None or topic in self.topics or message.type in _CRITICAL_TYPES:
            self.buffer.offer(message)

    def close(self) -> None:
        self._broker.unsubscribe(self)


class FrameBroker:
    """Non-blocking latest-state publisher for TrafficVerse-owned UI data."""

    def __init__(self, *, critical_capacity: int = 64) -> None:
        self._critical_capacity = critical_capacity
        self._subscriptions: dict[UUID, set[Subscription]] = {}
        self._latest_frames: dict[UUID, SimulationFrame] = {}

    async def publish_frame(self, frame: SimulationFrame) -> None:
        experiment_id = frame.traffic.experiment_id
        self._latest_frames[experiment_id] = frame
        messages = [
            make_envelope(
                "vehicle.delta",
                experiment_id,
                simulation_time_ms=frame.traffic.simulation_time_ms,
                sequence=frame.traffic.sequence,
                payload={
                    "vehicles": [
                        vehicle.model_dump(mode="json") for vehicle in frame.traffic.vehicles
                    ],
                    "collision_vehicle_ids": list(frame.traffic.collision_vehicle_ids),
                },
            ),
            make_envelope(
                "traffic_light.delta",
                experiment_id,
                simulation_time_ms=frame.traffic.simulation_time_ms,
                sequence=frame.traffic.sequence,
                payload={
                    "traffic_lights": [
                        light.model_dump(mode="json") for light in frame.traffic.traffic_lights
                    ]
                },
            ),
        ]
        for event in frame.events:
            messages.append(
                make_envelope(
                    "event.created",
                    experiment_id,
                    simulation_time_ms=event.simulation_time_ms,
                    sequence=frame.traffic.sequence,
                    payload=event.model_dump(mode="json"),
                )
            )
        for message in messages:
            self.publish(message)

    def publish(self, message: WebSocketEnvelope) -> None:
        for subscription in tuple(self._subscriptions.get(message.experiment_id, ())):
            subscription.offer(message)

    def subscribe(self, experiment_id: UUID) -> Subscription:
        subscription = Subscription(
            self,
            experiment_id,
            critical_capacity=self._critical_capacity,
        )
        self._subscriptions.setdefault(experiment_id, set()).add(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        subscriptions = self._subscriptions.get(subscription.experiment_id)
        if subscriptions is not None:
            subscriptions.discard(subscription)
            if not subscriptions:
                self._subscriptions.pop(subscription.experiment_id, None)
        subscription.buffer.close()

    def set_topics(
        self, subscription: Subscription, topics: frozenset[str], *, max_hz: float
    ) -> None:
        subscription.topics = topics
        subscription.max_hz = max_hz

    def world_snapshot(self, experiment_id: UUID) -> WebSocketEnvelope | None:
        frame = self._latest_frames.get(experiment_id)
        if frame is None:
            return None
        return make_envelope(
            "world.snapshot",
            experiment_id,
            simulation_time_ms=frame.traffic.simulation_time_ms,
            sequence=frame.traffic.sequence,
            payload=frame.model_dump(mode="json"),
        )
