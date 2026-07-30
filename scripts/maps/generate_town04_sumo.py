#!/usr/bin/env python3
"""Generate deterministic Town04 SUMO assets from the tracked OpenDRIVE file.

Run from the repository root:
  python scripts/maps/generate_town04_sumo.py
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from trafficverse.maps.sumo_display import augment_geojson_with_sumo_display

GENERATED_COMMENT = re.compile(r"\n?<!-- generated .*?-->\n?", re.DOTALL)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--map-dir",
        type=Path,
        default=Path("configs/maps/town04"),
    )
    parser.add_argument(
        "--display-only",
        action="store_true",
        help="only rebuild display geometry from the tracked SUMO network",
    )
    args = parser.parse_args()
    map_directory = args.map_dir.resolve()
    if not args.display_only:
        xodr_path = map_directory / "Town04.xodr"
        with tempfile.TemporaryDirectory(prefix="trafficverse-sumo-") as temporary:
            temporary_directory = Path(temporary)
            temporary_network = temporary_directory / "Town04.net.xml"
            temporary_routes = temporary_directory / "Town04.rou.xml"
            _run_netconvert(xodr_path, temporary_network)
            _run_random_trips(temporary_network, temporary_routes)
            network_text = GENERATED_COMMENT.sub(
                "\n", temporary_network.read_text(encoding="utf-8")
            )
            (map_directory / "Town04.net.xml").write_text(network_text, encoding="utf-8")
            _write_routes(temporary_routes, map_directory / "Town04.rou.xml")
        _write_vtypes(map_directory / "vtypes.rou.xml")
        _write_sumocfg(map_directory / "map.sumocfg")
    augment_geojson_with_sumo_display(
        map_directory / "network.geojson", map_directory / "Town04.net.xml"
    )
    _update_manifest(map_directory)
    return 0


def _run_netconvert(xodr_path: Path, output_path: Path) -> None:
    subprocess.run(
        (
            "netconvert",
            "--opendrive-files",
            str(xodr_path),
            "--output-file",
            str(output_path),
            "--geometry.remove",
            "--opendrive.curve-resolution",
            "1",
            "--opendrive.import-all-lanes",
            "--tls.guess",
            "--tls.discard-simple",
            "--tls.join",
        ),
        check=True,
    )


def _run_random_trips(network_path: Path, route_path: Path) -> None:
    subprocess.run(
        (
            "python3",
            "/usr/share/sumo/tools/randomTrips.py",
            "-n",
            str(network_path),
            "-r",
            str(route_path),
            "-o",
            str(network_path.parent / "Town04.trips.xml"),
            "-b",
            "0",
            "-e",
            "25",
            "-p",
            "0.5",
            "--seed",
            "42",
            "--validate",
            "--vehicle-class",
            "passenger",
            "--prefix",
            "vehicle-",
            "--trip-attributes",
            'departSpeed="max"',
        ),
        check=True,
    )


def _write_routes(source_path: Path, output_path: Path) -> None:
    source = ElementTree.parse(source_path).getroot()
    root = ElementTree.Element(
        "routes",
        {
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xsi:noNamespaceSchemaLocation": "http://sumo.dlr.de/xsd/routes_file.xsd",
        },
    )
    for vehicle in source.findall("vehicle"):
        vehicle.attrib["type"] = "passenger"
        root.append(vehicle)
    ElementTree.indent(root, space="    ")
    payload = ElementTree.tostring(root, encoding="unicode", short_empty_elements=True)
    output_path.write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n{payload}\n', encoding="utf-8")


def _write_vtypes(output_path: Path) -> None:
    output_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<routes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
        xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/routes_file.xsd">
    <vType id="passenger" vClass="passenger" length="4.5" minGap="2.5"
           accel="2.5" decel="4.0" emergencyDecel="8.0" sigma="0.5"
           carFollowModel="Krauss" laneChangeModel="LC2013"/>
</routes>
""",
        encoding="utf-8",
    )


def _write_sumocfg(output_path: Path) -> None:
    output_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<configuration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/sumoConfiguration.xsd">
    <input>
        <net-file value="Town04.net.xml"/>
        <route-files value="vtypes.rou.xml,Town04.rou.xml"/>
    </input>
    <time>
        <begin value="0"/>
        <step-length value="0.05"/>
    </time>
    <processing>
        <time-to-teleport value="-1"/>
    </processing>
    <report>
        <no-step-log value="true"/>
        <duration-log.disable value="true"/>
    </report>
</configuration>
""",
        encoding="utf-8",
    )


def _update_manifest(map_directory: Path) -> None:
    manifest_path = map_directory / "manifest.yaml"
    tracked = (
        "Town04.xodr",
        "Town04.net.xml",
        "Town04.rou.xml",
        "vtypes.rou.xml",
        "map.sumocfg",
        "network.geojson",
        "network.json",
        "routes.yaml",
        "signals.yaml",
    )
    checksums = {
        name: hashlib.sha256((map_directory / name).read_bytes()).hexdigest() for name in tracked
    }
    files = "\n".join(f"  {name}: sha256:{checksums[name]}" for name in tracked)
    manifest_path.write_text(
        f"""schema_version: '2.0'
map_id: town04-sumo-1.27.1-v2
sumo_version: 1.27.1
network_schema_version: traffic-network/1.0
compiler_version: 1.1.0
source_repository: local-opendrive
source_ref: 294096eb1c38eabf246e4f3a9cdab704e33a7f4c
sumo_generation_command: python scripts/maps/generate_town04_sumo.py --map-dir configs/maps/town04
validated: true
files:
{files}
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
