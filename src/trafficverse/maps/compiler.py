"""Deterministic MVP compiler from OpenDRIVE to SUMO-oriented traffic assets."""

import hashlib
import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import yaml

from trafficverse.domain.models.common import Vector3
from trafficverse.maps.errors import MapCompileError
from trafficverse.maps.models import (
    MAP_COMPILER_VERSION,
    NETWORK_SCHEMA_VERSION,
    Lane,
    LaneLink,
    RoadNetwork,
    TrafficSignal,
)
from trafficverse.maps.validation import shortest_route, validate_network


@dataclass(frozen=True, slots=True)
class MapCompileResult:
    network_path: Path
    geojson_path: Path
    manifest_path: Path
    lane_count: int
    link_count: int
    signal_count: int


@dataclass(frozen=True, slots=True)
class _LaneDraft:
    lane: Lane
    lane_element: ET.Element


def _number(element: ET.Element, name: str, default: float = 0.0) -> float:
    return float(element.attrib.get(name, default))


def _poly(element: ET.Element | None, value: float) -> float:
    if element is None:
        return 0.0
    return sum(
        _number(element, coefficient) * value**power for power, coefficient in enumerate("abcd")
    )


def _geometry_point(geometry: ET.Element, ds: float) -> tuple[float, float, float]:
    x, y, heading = (_number(geometry, key) for key in ("x", "y", "hdg"))
    child = next(iter(geometry), None)
    if child is None:
        raise MapCompileError("planView geometry has no primitive")
    if child.tag == "line":
        return x + ds * math.cos(heading), y + ds * math.sin(heading), heading
    if child.tag == "arc":
        curvature = _number(child, "curvature")
        if abs(curvature) < 1e-12:
            return x + ds * math.cos(heading), y + ds * math.sin(heading), heading
        end_heading = heading + curvature * ds
        return (
            x + (math.sin(end_heading) - math.sin(heading)) / curvature,
            y - (math.cos(end_heading) - math.cos(heading)) / curvature,
            end_heading,
        )
    if child.tag == "spiral":
        length = _number(geometry, "length")
        start = _number(child, "curvStart")
        end = _number(child, "curvEnd")
        steps = max(1, int(math.ceil(ds / 0.5)))
        delta = ds / steps
        px, py, current_heading = x, y, heading
        for index in range(steps):
            mid = (index + 0.5) * delta
            curvature = start + (end - start) * mid / length
            mid_heading = current_heading + curvature * delta / 2.0
            px += delta * math.cos(mid_heading)
            py += delta * math.sin(mid_heading)
            current_heading += curvature * delta
        return px, py, current_heading
    if child.tag in {"poly3", "paramPoly3"}:
        parameter = ds
        if child.tag == "paramPoly3" and child.attrib.get("pRange", "normalized") == "normalized":
            parameter = ds / _number(geometry, "length")
        u = parameter if child.tag == "poly3" else _poly(_prefixed(child, "U"), parameter)
        v = _poly(_prefixed(child, "V") if child.tag == "paramPoly3" else child, parameter)
        epsilon = 1e-4
        next_parameter = parameter + epsilon
        next_u = (
            next_parameter if child.tag == "poly3" else _poly(_prefixed(child, "U"), next_parameter)
        )
        next_v = _poly(
            _prefixed(child, "V") if child.tag == "paramPoly3" else child,
            next_parameter,
        )
        local_heading = math.atan2(next_v - v, next_u - u)
        return (
            x + u * math.cos(heading) - v * math.sin(heading),
            y + u * math.sin(heading) + v * math.cos(heading),
            heading + local_heading,
        )
    raise MapCompileError(f"unsupported critical OpenDRIVE geometry: {child.tag}")


def _prefixed(element: ET.Element, suffix: str) -> ET.Element:
    attributes = {
        coefficient: element.attrib.get(f"{coefficient}{suffix}", "0") for coefficient in "abcd"
    }
    return ET.Element("poly", attributes)


def _reference_point(road: ET.Element, s: float) -> tuple[float, float, float, float]:
    geometries = list(road.findall("./planView/geometry"))
    if not geometries:
        raise MapCompileError(f"road {road.attrib.get('id')} has no planView geometry")
    selected = geometries[0]
    for geometry in geometries:
        if _number(geometry, "s") <= s + 1e-9:
            selected = geometry
        else:
            break
    ds = min(max(0.0, s - _number(selected, "s")), _number(selected, "length"))
    x, y, heading = _geometry_point(selected, ds)
    elevations = road.findall("./elevationProfile/elevation")
    elevation = None
    for candidate in elevations:
        if _number(candidate, "s") <= s + 1e-9:
            elevation = candidate
    z = _poly(elevation, s - _number(elevation, "s")) if elevation is not None else 0.0
    return x, y, z, heading


def _lane_width(lane: ET.Element, section_s: float) -> float:
    selected = None
    for width in lane.findall("width"):
        if _number(width, "sOffset") <= section_s + 1e-9:
            selected = width
    if selected is None:
        return 0.1
    return max(0.1, _poly(selected, section_s - _number(selected, "sOffset")))


def _lane_offset(road: ET.Element, s: float) -> float:
    selected = None
    for offset in road.findall("./lanes/laneOffset"):
        if _number(offset, "s") <= s + 1e-9:
            selected = offset
    return _poly(selected, s - _number(selected, "s")) if selected is not None else 0.0


def _lane_id(road_id: str, section_index: int, source_lane_id: int) -> str:
    return f"road:{road_id}:section:{section_index}:lane:{source_lane_id}"


def _speed_limit(road: ET.Element, lane: ET.Element) -> float:
    speed = lane.find("speed")
    if speed is None:
        speed = road.find("./type/speed")
    if speed is None or speed.attrib.get("max") in {None, "no limit", "undefined"}:
        return 13.8888888889
    maximum = _number(speed, "max")
    unit = speed.attrib.get("unit", "m/s")
    if unit in {"km/h", "kmh", "kph"}:
        maximum /= 3.6
    elif unit == "mph":
        maximum *= 0.44704
    return max(1.0, maximum)


class OpenDriveMapCompiler:
    """Compile the OpenDRIVE subset needed by the pinned Town04 MVP."""

    def __init__(self, *, sample_distance_m: float = 5.0) -> None:
        if sample_distance_m <= 0:
            raise ValueError("sample_distance_m must be positive")
        self._sample_distance_m = sample_distance_m

    def compile(
        self,
        source: Path,
        output_directory: Path,
        *,
        map_id: str,
        sumo_version: str = "1.27.1",
        source_repository: str = "local-opendrive",
        source_ref: str = "unversioned",
        sumo_generation_command: str = "netconvert --opendrive-files <source>",
    ) -> MapCompileResult:
        try:
            root = ET.fromstring(source.read_bytes())
        except (OSError, ET.ParseError) as error:
            raise MapCompileError(f"invalid OpenDRIVE XML: {source}: {error}") from error
        if root.tag != "OpenDRIVE":
            raise MapCompileError("OpenDRIVE root element is required")
        network = self._build_network(root, map_id)
        validate_network(network)
        output_directory.mkdir(parents=True, exist_ok=True)
        network_path = output_directory / "network.json"
        network_path.write_text(
            json.dumps(
                network.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        geojson_path = output_directory / "network.geojson"
        geojson_path.write_text(self._geojson(network), encoding="utf-8")
        self._write_demo_assets(network, output_directory)
        copied_source = output_directory / source.name
        if copied_source.resolve() != source.resolve():
            copied_source.write_bytes(source.read_bytes())
        files = {}
        asset_names = {
            source.name,
            "network.json",
            "network.geojson",
            "routes.yaml",
            "signals.yaml",
        }
        for name in sorted(asset_names):
            path = output_directory / name
            files[name] = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        manifest = {
            "schema_version": "2.0",
            "map_id": map_id,
            "sumo_version": sumo_version,
            "network_schema_version": NETWORK_SCHEMA_VERSION,
            "compiler_version": MAP_COMPILER_VERSION,
            "source_repository": source_repository,
            "source_ref": source_ref,
            "sumo_generation_command": sumo_generation_command,
            "validated": True,
            "files": files,
        }
        manifest_path = output_directory / "manifest.yaml"
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=True), encoding="utf-8")
        return MapCompileResult(
            network_path,
            geojson_path,
            manifest_path,
            len(network.lanes),
            len(network.links),
            len(network.signals),
        )

    def _build_network(self, root: ET.Element, map_id: str) -> RoadNetwork:
        roads = {road.attrib["id"]: road for road in root.findall("road")}
        drafts: dict[str, _LaneDraft] = {}
        section_counts: dict[str, int] = {}
        for road_id, road in sorted(roads.items()):
            sections = road.findall("./lanes/laneSection")
            section_counts[road_id] = len(sections)
            road_length = _number(road, "length")
            for section_index, section in enumerate(sections):
                start = _number(section, "s")
                end = (
                    _number(sections[section_index + 1], "s")
                    if section_index + 1 < len(sections)
                    else road_length
                )
                driving = [
                    lane
                    for lane in section.findall("./left/lane") + section.findall("./right/lane")
                    if lane.attrib.get("type") == "driving" and int(lane.attrib["id"]) != 0
                ]
                source_ids = {int(lane.attrib["id"]) for lane in driving}
                for lane_element in driving:
                    source_id = int(lane_element.attrib["id"])
                    samples = max(2, int(math.ceil((end - start) / self._sample_distance_m)) + 1)
                    points: list[Vector3] = []
                    widths: list[float] = []
                    same_side = sorted(
                        (value for value in source_ids if value * source_id > 0), key=abs
                    )
                    for sample in range(samples):
                        s = start + (end - start) * sample / (samples - 1)
                        local_s = s - start
                        width = _lane_width(lane_element, local_s)
                        widths.append(width)
                        offset = _lane_offset(road, s)
                        for candidate_id in same_side:
                            candidate = next(
                                item for item in driving if int(item.attrib["id"]) == candidate_id
                            )
                            candidate_width = _lane_width(candidate, local_s)
                            if abs(candidate_id) < abs(source_id):
                                offset += math.copysign(candidate_width, source_id)
                            elif candidate_id == source_id:
                                offset += math.copysign(candidate_width / 2.0, source_id)
                        x, y, z, heading = _reference_point(road, s)
                        points.append(
                            Vector3(
                                x=x - math.sin(heading) * offset,
                                y=y + math.cos(heading) * offset,
                                z=z,
                            )
                        )
                    if source_id > 0:
                        points.reverse()
                    identifier = _lane_id(road_id, section_index, source_id)
                    toward_center = source_id - int(math.copysign(1, source_id))
                    away_center = source_id + int(math.copysign(1, source_id))
                    left = (
                        _lane_id(road_id, section_index, toward_center)
                        if toward_center in source_ids
                        else None
                    )
                    right = (
                        _lane_id(road_id, section_index, away_center)
                        if away_center in source_ids
                        else None
                    )
                    lane = Lane(
                        lane_id=identifier,
                        road_id=road_id,
                        section_index=section_index,
                        source_lane_id=source_id,
                        length_m=max(0.01, end - start),
                        width_m=sum(widths) / len(widths),
                        speed_limit_mps=_speed_limit(road, lane_element),
                        centerline=tuple(points),
                        left_lane_id=left,
                        right_lane_id=right,
                        junction_id=(
                            road.attrib.get("junction")
                            if road.attrib.get("junction") != "-1"
                            else None
                        ),
                    )
                    drafts[identifier] = _LaneDraft(lane, lane_element)
        successors = self._successors(root, roads, drafts, section_counts)
        predecessors: dict[str, set[str]] = {lane_id: set() for lane_id in drafts}
        for source, targets in successors.items():
            for target in targets:
                predecessors[target].add(source)
        links: list[LaneLink] = []
        for source, targets in sorted(successors.items()):
            for target in sorted(targets):
                links.append(
                    LaneLink(
                        link_id=f"link:{source}->{target}",
                        from_lane_id=source,
                        to_lane_id=target,
                        junction_id=drafts[target].lane.junction_id,
                    )
                )
        signals = self._signals(roads, drafts, links)
        signal_for_link = {
            link_id: signal.signal_id
            for signal in signals
            for link_id in signal.controlled_link_ids
        }
        links = [
            link.model_copy(
                update={
                    "signal_id": signal_for_link.get(link.link_id),
                    "stop_line_s_m": (
                        drafts[link.from_lane_id].lane.length_m
                        if link.link_id in signal_for_link
                        else None
                    ),
                }
            )
            for link in links
        ]
        lanes = [
            draft.lane.model_copy(
                update={
                    "successor_ids": tuple(sorted(successors[lane_id])),
                    "predecessor_ids": tuple(sorted(predecessors[lane_id])),
                }
            )
            for lane_id, draft in sorted(drafts.items())
        ]
        if not lanes:
            raise MapCompileError("OpenDRIVE contains no driving lanes")
        return RoadNetwork(
            map_id=map_id,
            lanes=tuple(lanes),
            links=tuple(sorted(links, key=lambda item: item.link_id)),
            signals=tuple(signals),
        )

    @staticmethod
    def _successors(
        root: ET.Element,
        roads: dict[str, ET.Element],
        drafts: dict[str, _LaneDraft],
        section_counts: dict[str, int],
    ) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {lane_id: set() for lane_id in drafts}
        for lane_id, draft in drafts.items():
            lane = draft.lane
            direction = 1 if lane.source_lane_id < 0 else -1
            next_section = lane.section_index + direction
            link_tag = "successor" if direction == 1 else "predecessor"
            lane_link = draft.lane_element.find(f"./link/{link_tag}")
            target_source = (
                int(lane_link.attrib["id"]) if lane_link is not None else lane.source_lane_id
            )
            if 0 <= next_section < section_counts[lane.road_id]:
                target = _lane_id(lane.road_id, next_section, target_source)
                if target in drafts:
                    result[lane_id].add(target)
                continue
            road = roads[lane.road_id]
            road_link = road.find(f"./link/{link_tag}")
            if road_link is not None and road_link.attrib.get("elementType") == "road":
                target_road = road_link.attrib["elementId"]
                contact = road_link.attrib.get("contactPoint", "start")
                section = 0 if contact == "start" else section_counts[target_road] - 1
                target = _lane_id(target_road, section, target_source)
                if target in drafts:
                    result[lane_id].add(target)
            if road_link is not None and road_link.attrib.get("elementType") == "junction":
                junction_id = road_link.attrib["elementId"]
                for connection in root.findall(f"./junction[@id='{junction_id}']/connection"):
                    if connection.attrib.get("incomingRoad") != lane.road_id:
                        continue
                    connecting = connection.attrib["connectingRoad"]
                    contact = connection.attrib.get("contactPoint", "start")
                    section = 0 if contact == "start" else section_counts[connecting] - 1
                    for lane_mapping in connection.findall("laneLink"):
                        if int(lane_mapping.attrib["from"]) == lane.source_lane_id:
                            target = _lane_id(connecting, section, int(lane_mapping.attrib["to"]))
                            if target in drafts:
                                result[lane_id].add(target)
        return result

    @staticmethod
    def _signals(
        roads: dict[str, ET.Element], drafts: dict[str, _LaneDraft], links: list[LaneLink]
    ) -> list[TrafficSignal]:
        signals: list[TrafficSignal] = []
        for road_id, road in sorted(roads.items()):
            for element in road.findall("./signals/signal"):
                if element.attrib.get("dynamic", "no").lower() not in {"yes", "true", "1"}:
                    continue
                source_id = element.attrib.get("id")
                if not source_id:
                    raise MapCompileError(f"dynamic signal on road {road_id} has no id")
                candidates = tuple(
                    link.link_id
                    for link in links
                    if drafts[link.from_lane_id].lane.road_id == road_id
                )
                if not candidates:
                    raise MapCompileError(
                        f"dynamic signal {source_id} on road {road_id} controls no lane links"
                    )
                signals.append(
                    TrafficSignal(
                        signal_id=f"signal:{source_id}",
                        opendrive_id=source_id,
                        road_id=road_id,
                        controlled_link_ids=tuple(sorted(candidates)),
                    )
                )
        return sorted(signals, key=lambda item: item.signal_id)

    @staticmethod
    def _geojson(network: RoadNetwork) -> str:
        features: list[dict[str, object]] = [
            {
                "type": "Feature",
                "id": lane.lane_id,
                "properties": {
                    "lane_id": lane.lane_id,
                    "road_id": lane.road_id,
                    "speed_limit_mps": lane.speed_limit_mps,
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[point.x, point.y, point.z] for point in lane.centerline],
                },
            }
            for lane in network.lanes
        ]
        lanes = {lane.lane_id: lane for lane in network.lanes}
        links = {link.link_id: link for link in network.links}
        for signal in network.signals:
            controlled_link = links[sorted(signal.controlled_link_ids)[0]]
            stop_lane = lanes[controlled_link.from_lane_id]
            stop_point = stop_lane.centerline[-1]
            features.append(
                {
                    "type": "Feature",
                    "id": signal.signal_id,
                    "properties": {
                        "signal_id": signal.signal_id,
                        "opendrive_id": signal.opendrive_id,
                        "road_id": signal.road_id,
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [stop_point.x, stop_point.y, stop_point.z],
                    },
                }
            )
        return (
            json.dumps(
                {"type": "FeatureCollection", "features": features},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    @staticmethod
    def _write_demo_assets(network: RoadNetwork, output_directory: Path) -> None:
        usable = [lane.lane_id for lane in network.lanes if lane.successor_ids]
        if not usable:
            raise MapCompileError("network has no reachable route")
        routes = []
        for index in range(50):
            lane_path = shortest_route(network, usable[index % len(usable)])
            if len(lane_path) < 2:
                lane_path = (usable[index % len(usable)],)
            routes.append(
                {
                    "route_id": f"town04-route-{index:03d}",
                    "lane_ids": list(lane_path),
                    "vehicle_id": f"vehicle-{index:03d}",
                    "depart_ms": index * 500,
                    "desired_speed_mps": 10.0 + (index % 4),
                }
            )
        (output_directory / "routes.yaml").write_text(
            yaml.safe_dump({"schema_version": "1.0", "routes": routes}, sort_keys=True),
            encoding="utf-8",
        )
        signal_payload = {
            "schema_version": "1.0",
            "programs": [
                {
                    "signal_id": signal.signal_id,
                    "phases": [
                        {"color": "GREEN", "duration_ms": 20000},
                        {"color": "RED", "duration_ms": 20000},
                    ],
                }
                for signal in network.signals
            ],
        }
        (output_directory / "signals.yaml").write_text(
            yaml.safe_dump(signal_payload, sort_keys=True), encoding="utf-8"
        )
