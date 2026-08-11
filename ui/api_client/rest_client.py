"""Asynchronous Qt REST client for the TrafficVerse resource API."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

from PySide6.QtCore import QFile, QIODeviceBase, QObject, QSaveFile, QUrl, QUrlQuery, Signal
from PySide6.QtNetwork import (
    QHttpMultiPart,
    QHttpPart,
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)

from ui.models import SimulationConfigurationDraft


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

    def list_simulations(self, workspace_id: UUID | None = None) -> None:
        parameters = {"workspace_id": str(workspace_id)} if workspace_id is not None else None
        self._get("simulations.list", "/api/v1/simulations", parameters)

    def get_simulation(self, run_id: str) -> None:
        self._get(f"simulation.get:{run_id}", f"/api/v1/simulations/{run_id}")

    def get_simulation_network(self, run_id: str) -> None:
        self._get(
            f"simulation.network:{run_id}",
            f"/api/v1/simulations/{run_id}/network",
        )

    def get_simulation_replay(self, run_id: str, from_time_ms: int = 0) -> None:
        self._get(
            f"simulation.replay:{run_id}:{from_time_ms}",
            f"/api/v1/simulations/{run_id}/replay",
            {"from_time_ms": str(from_time_ms), "limit": "2000"},
        )

    def export_simulation(self, run_id: str, target: Path) -> None:
        operation = f"simulation.export:{run_id}"
        reply = self._network.get(
            QNetworkRequest(self._url(f"/api/v1/simulations/{run_id}/export"))
        )
        reply.finished.connect(lambda: self._finish_download(operation, target, reply))

    def list_workspaces(self, query: str | None = None) -> None:
        parameters = {"query": query} if query else None
        self._get("workspaces.list", "/api/v1/workspaces", parameters)

    def get_workspace_overview(self, workspace_id: UUID) -> None:
        self._get(
            f"workspace.overview:{workspace_id}",
            f"/api/v1/workspaces/{workspace_id}/overview",
        )

    def create_workspace(self, name: str, description: str) -> None:
        self._post_json(
            "workspace.create",
            "/api/v1/workspaces",
            {"name": name, "description": description},
        )

    def update_workspace(self, workspace_id: UUID, name: str, description: str) -> None:
        self._patch_json(
            f"workspace.update:{workspace_id}",
            f"/api/v1/workspaces/{workspace_id}",
            {"name": name, "description": description},
        )

    def delete_workspace(self, workspace_id: UUID) -> None:
        operation = f"workspace.delete:{workspace_id}"
        self._watch(
            operation,
            self._network.deleteResource(
                QNetworkRequest(self._url(f"/api/v1/workspaces/{workspace_id}"))
            ),
        )

    def list_agent_assets(self, workspace_id: UUID) -> None:
        self._get(
            f"agent-assets.list:{workspace_id}",
            f"/api/v1/workspaces/{workspace_id}/agent-assets",
        )

    def configure_agent_asset(
        self,
        workspace_id: UUID,
        name: str,
        api_base_url: str,
        model_id: str,
        credential_env_var: str,
        description: str,
    ) -> None:
        self._post_json(
            f"agent-assets.create:{workspace_id}",
            f"/api/v1/workspaces/{workspace_id}/agent-assets",
            {
                "name": name,
                "api_base_url": api_base_url,
                "model_id": model_id,
                "credential_env_var": credential_env_var,
                "description": description,
            },
        )

    def delete_agent_asset(self, workspace_id: UUID, agent_api_id: UUID) -> None:
        operation = f"agent-assets.delete:{workspace_id}:{agent_api_id}"
        self._watch(
            operation,
            self._network.deleteResource(
                QNetworkRequest(
                    self._url(f"/api/v1/workspaces/{workspace_id}/agent-assets/{agent_api_id}")
                )
            ),
        )

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

    def save_simulation_configuration(
        self,
        workspace_id: UUID,
        scenario_id: UUID,
        configuration: SimulationConfigurationDraft,
    ) -> None:
        self._post_json(
            "simulation-configuration.save",
            "/api/v1/simulation-configurations",
            {
                "workspace_id": str(workspace_id),
                "scenario_id": str(scenario_id),
                **configuration.model_dump(mode="json"),
            },
        )

    def create_experiment(
        self,
        workspace_id: UUID,
        scenario_id: UUID,
        map_id: str,
        configuration_id: str | None = None,
        run_kind: str = "simulation",
    ) -> None:
        payload: dict[str, object] = {
            "workspace_id": str(workspace_id),
            "scenario_id": str(scenario_id),
            "map_id": map_id,
        }
        if configuration_id is not None:
            payload["configuration_id"] = configuration_id
            payload["run_kind"] = run_kind
        self._post_json(
            "experiment.create",
            "/api/v1/experiments",
            payload,
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

    def _get(
        self,
        operation: str,
        path: str,
        parameters: Mapping[str, str] | None = None,
    ) -> None:
        self._watch(operation, self._network.get(QNetworkRequest(self._url(path, parameters))))

    def _post_json(self, operation: str, path: str, payload: dict[str, object]) -> None:
        request = QNetworkRequest(self._url(path))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        reply = self._network.post(
            request,
            json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        )
        self._watch(operation, reply)

    def _patch_json(self, operation: str, path: str, payload: dict[str, object]) -> None:
        request = QNetworkRequest(self._url(path))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        reply = self._network.sendCustomRequest(
            request,
            b"PATCH",
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

    def _finish_download(self, operation: str, target: Path, reply: QNetworkReply) -> None:
        try:
            raw = bytes(reply.readAll().data())
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.request_failed.emit(operation, self._error_message(reply, raw))
                return
            destination = QSaveFile(str(target))
            if not destination.open(QIODeviceBase.OpenModeFlag.WriteOnly):
                self.request_failed.emit(operation, f"无法写入导出文件：{target.name}")
                return
            if destination.write(raw) != len(raw) or not destination.commit():
                destination.cancelWriting()
                self.request_failed.emit(operation, f"导出文件写入失败：{target.name}")
                return
            self.request_succeeded.emit(operation, str(target))
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

    def _url(
        self,
        path: str,
        parameters: Mapping[str, str] | None = None,
    ) -> QUrl:
        url = QUrl(f"{self._base_url}{path}")
        if parameters:
            query = QUrlQuery()
            for key, value in parameters.items():
                query.addQueryItem(key, value)
            url.setQuery(query)
        return url
