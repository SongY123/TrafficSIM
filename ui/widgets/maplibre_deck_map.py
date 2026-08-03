"""MapLibre/deck.gl host widget with a narrow JavaScript bridge."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QWidget

from ui.models import ReplayRoadResult, TrafficLight, Vehicle


class _MapBridge(QObject):
    ready = Signal()
    vehicle_selected = Signal(str)

    @Slot()
    def mapReady(self) -> None:  # noqa: N802 - Qt/JS protocol name
        self.ready.emit()

    @Slot(str)
    def selectVehicle(self, vehicle_id: str) -> None:  # noqa: N802 - Qt/JS protocol name
        self.vehicle_selected.emit(vehicle_id)


class MapLibreDeckMapWidget(QWebEngineView):
    """Host the offline map bundle and forward versioned UI model snapshots."""

    vehicle_selected = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        load_page: bool = True,
        page_mode: str = "live",
    ) -> None:
        super().__init__(parent)
        if page_mode not in {"live", "replay"}:
            raise ValueError(f"Unsupported map page mode: {page_mode}")
        self._page_mode = page_mode
        self._ready = False
        self._pending: dict[str, object] = {}
        self._bridge = _MapBridge(self)
        self._bridge.ready.connect(self._map_ready)
        self._bridge.vehicle_selected.connect(self.vehicle_selected)
        channel = QWebChannel(self.page())
        channel.registerObject("trafficVerseBridge", self._bridge)
        self.page().setWebChannel(channel)
        self.loadStarted.connect(self._loading)
        self.loadFinished.connect(self._loaded)
        if load_page:
            page = Path(__file__).resolve().parents[1] / "web/map/index.html"
            url = QUrl.fromLocalFile(str(page))
            if page_mode != "live":
                url.setQuery(f"mode={page_mode}")
            self.load(url)

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
    def set_traffic_lights(self, lights: object) -> None:
        values = lights if isinstance(lights, tuple) else ()
        payload = [
            light.model_dump(mode="json") for light in values if isinstance(light, TrafficLight)
        ]
        self._dispatch("setTrafficLights", payload)

    @Slot(object)
    def set_road_results(self, results: object) -> None:
        values = results if isinstance(results, tuple) else ()
        payload = [
            {
                "road_id": item.road_id,
                "average_speed_mps": item.average_speed_mps,
                "congestion_level": item.congestion_level,
                "flow_veh_per_h": item.flow_veh_per_h,
                "queue_length": item.queue_length,
            }
            for item in values
            if isinstance(item, ReplayRoadResult)
        ]
        self._dispatch("setRoadResults", payload)

    @Slot(str)
    def set_theme(self, theme: str) -> None:
        if theme in {"dark", "light"}:
            self._dispatch("setTheme", theme)

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
