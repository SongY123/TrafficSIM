"""SUMO traffic-engine port; no third-party SDK types may appear here."""

from collections.abc import Mapping
from typing import Protocol

from trafficverse.config.models import SumoConfig
from trafficverse.domain.models import (
    ComponentHealth,
    ControlCommand,
    TrafficSnapshot,
)


class TrafficEnginePort(Protocol):
    def load(self, config: SumoConfig) -> None: ...

    def apply_controls(self, commands: Mapping[str, ControlCommand]) -> None: ...

    def step(self, target_time_ms: int) -> TrafficSnapshot: ...

    def health(self) -> ComponentHealth: ...

    def close(self) -> None: ...
