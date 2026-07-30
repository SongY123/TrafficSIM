"""Asynchronous Qt REST client for the TrafficVerse resource API."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from PySide6.QtCore import QFile, QIODeviceBase, QObject, QUrl, QUrlQuery, Signal
from PySide6.QtNetwork import (
    QHttpMultiPart,
    QHttpPart,
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)


class RestApiClient(QObject):
    request_succeeded = Signal(str, object)
    request_failed = Signal(str, str)

    def __init__(self, base_url: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._base_url = base_url.rstrip("/")
        self._network = QNetworkAccessManager(self)

    @property
    def base_url(self) -> str:
        return self._base_url

    def check_readiness(self) -> None:
        self._get("ready", "/api/v1/ready")

    def check_health(self) -> None:
        self._get("health", "/api/v1/health")

    def list_maps(self) -> None:
        self._get("maps.list", "/api/v1/maps")

    def list_workspaces(
        self,
        query: str | None = None,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> None:
        url = self._url("/api/v1/workspaces")
        parameters = QUrlQuery()
        if query:
            parameters.addQueryItem("q", query)
        parameters.addQueryItem("offset", str(offset))
        parameters.addQueryItem("limit", str(limit))
        url.setQuery(parameters)
        self._watch("workspaces.list", self._network.get(QNetworkRequest(url)))

    def get_map_network(self, map_id: str) -> None:
        self._get(f"map.network:{map_id}", f"/api/v1/maps/{map_id}/network")

    def get_asset_map_network(self, map_id: str) -> None:
        self._get(f"asset.map.network:{map_id}", f"/api/v1/maps/{map_id}/network")

    def get_map_manifest(self, map_id: str) -> None:
        self._get(f"map.manifest:{map_id}", f"/api/v1/maps/{map_id}/manifest")

    def get_import_job(self, job_id: UUID) -> None:
        self._get(f"map.import:{job_id}", f"/api/v1/maps/import/{job_id}")

    def import_map(self, path: Path) -> None:
        operation = "map.import.submit"
        source = QFile(str(path), self)
        if not source.open(QIODeviceBase.OpenModeFlag.ReadOnly):
            self.request_failed.emit(operation, f"无法读取地图文件：{path.name}")
            source.deleteLater()
            return
        multipart = QHttpMultiPart(QHttpMultiPart.ContentType.FormDataType)
        part = QHttpPart()
        part.setHeader(
            QNetworkRequest.KnownHeaders.ContentDispositionHeader,
            f'form-data; name="file"; filename="{path.name}"',
        )
        part.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/xml")
        source.setParent(multipart)
        part.setBodyDevice(source)
        multipart.append(part)
        request = QNetworkRequest(self._url("/api/v1/maps/import"))
        reply = self._network.post(request, multipart)
        multipart.setParent(reply)
        self._watch(operation, reply)

    def create_experiment(self, scenario_id: UUID, map_id: str) -> None:
        self._post_json(
            "experiment.create",
            "/api/v1/experiments",
            {"scenario_id": str(scenario_id), "map_id": map_id},
        )

    def get_experiment(self, experiment_id: UUID) -> None:
        self._get(
            f"experiment.get:{experiment_id}",
            f"/api/v1/experiments/{experiment_id}",
        )

    def experiment_command(
        self,
        experiment_id: UUID,
        command: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        self._post_json(
            f"experiment.command:{command}",
            f"/api/v1/experiments/{experiment_id}/{command}",
            payload or {},
        )

    def _get(self, operation: str, path: str) -> None:
        self._watch(operation, self._network.get(QNetworkRequest(self._url(path))))

    def _post_json(self, operation: str, path: str, payload: dict[str, object]) -> None:
        request = QNetworkRequest(self._url(path))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        reply = self._network.post(
            request,
            json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        )
        self._watch(operation, reply)

    def _watch(self, operation: str, reply: QNetworkReply) -> None:
        reply.finished.connect(lambda: self._finish(operation, reply))

    def _finish(self, operation: str, reply: QNetworkReply) -> None:
        try:
            raw = bytes(reply.readAll().data())
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.request_failed.emit(operation, self._error_message(reply, raw))
                return
            payload = json.loads(raw.decode("utf-8")) if raw else None
            self.request_succeeded.emit(operation, payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            self.request_failed.emit(operation, f"服务器返回了无法解析的数据：{error}")
        finally:
            reply.deleteLater()

    @staticmethod
    def _error_message(reply: QNetworkReply, raw: bytes) -> str:
        try:
            payload = json.loads(raw.decode("utf-8"))
            error = payload.get("error", {})
            message = error.get("message")
            if isinstance(message, str):
                return message
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            pass
        return reply.errorString()

    def _url(self, path: str) -> QUrl:
        return QUrl(f"{self._base_url}{path}")
