# TrafficVerse

TrafficVerse 是“SUMO 全局交通真值 + TrafficVerse 2D MapLibre/deck.gl”的交互式交通仿真系统。
SUMO 通过 TraCI 提供车辆、路线、车道、运动学状态、信号灯和仿真时间；TrafficVerse API 将标准
快照通过 REST/WebSocket 提供给自有 PySide6 页面。产品不嵌入 SUMO GUI。

当前产品已移除 CARLA、ROI 同步、RGB 图像链路和 native-window 托管。禁止安装、启动或恢复这些
已废止组件。架构决策见 [ADR-027](docs/ADR.md#adr-027--移除-carla产品聚焦-sumo--trafficverse-2d)。

## 固定版本与端点

- Python 3.10
- Node.js 16.20.2、npm 8.19.4（仅构建离线 Web 地图）
- SUMO 1.27.1：`127.0.0.1:8813`
- TrafficVerse API：`127.0.0.1:8000`
- 固定仿真步长：50 ms

## 安装

```bash
uv sync --frozen --extra sumo --extra ui
```

## 生成并校验 Town04 SUMO 资产

```bash
python scripts/maps/generate_town04_sumo.py
sumo -c configs/maps/town04/map.sumocfg --end 5
```

## 启动

只需依次启动 SUMO、API 和 UI：

```bash
sumo -c configs/maps/town04/map.sumocfg --remote-port 8813
uv run trafficverse serve --host 127.0.0.1 --port 8000
uv run trafficverse ui --api-url http://127.0.0.1:8000
```

调试时可把 `sumo` 换为 `sumo-gui`；该窗口保持独立，不属于 TrafficVerse 产品 UI。

二维页面使用仓库内置的 MapLibre/deck.gl 离线 bundle，运行时不需要 Node.js、CDN 或公网。
Town04 没有真实地理 `geoReference`，地图使用本地 OpenDRIVE/GeoJSON 派生的 OSM 风格道路分层，
不叠加会与仿真坐标错位的现实 OpenStreetMap 瓦片。车辆模型和全部 Web 资源均离线加载。
`network.geojson` 中的显示专用几何不参与车辆推进；运行中的车辆位置和灯色只来自 SUMO 快照。

刷新显示几何：

```bash
python scripts/maps/generate_town04_sumo.py --display-only
```

构建离线 Web 地图：

```bash
cd ui/web/map
npm ci
npm run build
```

仅在已验证的软件渲染环境需要：

```bash
uv run trafficverse ui \
  --api-url http://127.0.0.1:8000 \
  --allow-software-webgl
```

有受支持硬件 GPU 的桌面环境不要添加 `--allow-software-webgl`。

## 验证

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
```

真实 SUMO integration：

```bash
TRAFFICVERSE_SUMO_INTEGRATION=1 uv run pytest -m traffic \
  tests/integration/traffic/test_sumo_adapter.py
```

设计详情见 [PRD](docs/PRD.md)、[System Design](docs/SYSTEM_DESIGN.md)、
[ADR](docs/ADR.md)、[地图资产目录与支持格式](docs/MAP_ASSET_CATALOG.md) 和
[Agent Guide](docs/AGENT_DEVELOPMENT_GUIDE.md)。
