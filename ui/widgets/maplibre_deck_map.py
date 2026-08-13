"""MapLibre/deck.gl host widget with a narrow JavaScript bridge."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QWidget

from ui.models import TrafficLight, Vehicle


class _MapBridge(QObject):
    ready = Signal()
    vehicle_selected = Signal(str)
    maximize_requested = Signal()

    @Slot()
    def mapReady(self) -> None:  # noqa: N802 - Qt/JS protocol name
        self.ready.emit()

    @Slot(str)
    def selectVehicle(self, vehicle_id: str) -> None:  # noqa: N802 - Qt/JS protocol name
        self.vehicle_selected.emit(vehicle_id)

    @Slot()
    def toggleMapMaximize(self) -> None:  # noqa: N802 - Qt/JS protocol name
        self.maximize_requested.emit()


class MapLibreDeckMapWidget(QWebEngineView):
    """Host the offline map bundle and forward versioned UI model snapshots."""

    vehicle_selected = Signal(str)
    maximize_requested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        load_page: bool = True,
        show_legend: bool = True,
        show_maximize: bool = False,
    ) -> None:
        super().__init__(parent)
        self._ready = False
        self._pending: dict[str, object] = {}
        self._bridge = _MapBridge(self)
        self._bridge.ready.connect(self._map_ready)
        self._bridge.vehicle_selected.connect(self.vehicle_selected)
        self._bridge.maximize_requested.connect(self.maximize_requested)
        channel = QWebChannel(self.page())
        channel.registerObject("trafficVerseBridge", self._bridge)
        self.page().setWebChannel(channel)
        self.loadStarted.connect(self._loading)
        self.loadFinished.connect(self._loaded)
        self._dispatch("setLegendVisible", show_legend)
        self._dispatch("setMaximizeEnabled", show_maximize)
        if load_page:
            page = Path(__file__).resolve().parents[1] / "web/map/index.html"
            self.load(QUrl.fromLocalFile(str(page)))

    @Slot(object)
    def set_network(self, geojson: object) -> None:
        self._dispatch("setNetwork", geojson)

    @Slot(object)
    def set_vehicles(self, vehicles: object) -> None:
        values = vehicles if isinstance(vehicles, tuple) else ()
        payload = [
            vehicle.model_dump(mode="json") for vehicle in values if isinstance(vehicle, Vehicle)
        ]
        self._dispatch("setVehicles", payload)

    @Slot(object)
    def set_collision_vehicle_ids(self, vehicle_ids: object) -> None:
        values = vehicle_ids if isinstance(vehicle_ids, (tuple, list, set, frozenset)) else ()
        payload = sorted(value for value in values if isinstance(value, str))
        self._dispatch("setCollisionVehicleIds", payload)

    @Slot(object)
    def set_traffic_lights(self, lights: object) -> None:
        values = lights if isinstance(lights, tuple) else ()
        payload = [
            light.model_dump(mode="json") for light in values if isinstance(light, TrafficLight)
        ]
        self._dispatch("setTrafficLights", payload)

    @Slot(str)
    def set_theme(self, theme: str) -> None:
        if theme in {"dark", "light"}:
            self._dispatch("setTheme", theme)

    @Slot(bool)
    def set_maximized(self, maximized: bool) -> None:
        self._dispatch("setMaximized", maximized)

    def _dispatch(self, method: str, payload: object) -> None:
        self._pending[method] = payload
        if not self._ready:
            return
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self.page().runJavaScript(f"window.TrafficVerseMap.{method}({encoded});")
        self._pending.pop(method, None)

    def _loading(self) -> None:
        self._ready = False

    def _loaded(self, succeeded: bool) -> None:
        if not succeeded:
            self._ready = False

    def _map_ready(self) -> None:
        self._ready = True
        pending = tuple(self._pending.items())
        for method, payload in pending:
            self._dispatch(method, payload)
