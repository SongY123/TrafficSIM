"""Typed view models for the result replay page."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ReplayMetric:
    """One aggregate result metric displayed on the replay page."""

    label: str
    value: str
    detail: str


@dataclass(frozen=True, slots=True)
class ReplayTrendSeries:
    """One normalized time series for the replay trend chart."""

    label: str
    values: tuple[float, ...]
    color: str
    unit: str


@dataclass(frozen=True, slots=True)
class ReplayRoadResult:
    """Aggregated result values used to color a road result layer."""

    road_id: str
    average_speed_mps: float
    congestion_level: str
    flow_veh_per_h: float
    queue_length: float


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """Result data consumed by the presentation-only replay page."""

    experiment_id: UUID | None
    scenario_id: UUID
    map_id: str
    scenario_name: str
    map_name: str
    seed: int
    description: str
    started_at: datetime
    finished_at: datetime
    duration_s: float
    status: str
    end_status: str
    data_source: str
    metrics: tuple[ReplayMetric, ...]
    trend_labels: tuple[str, ...]
    trend_series: tuple[ReplayTrendSeries, ...]
    road_results: tuple[ReplayRoadResult, ...]

    @property
    def history_label(self) -> str:
        """Return the date/time label used by the replay history selector."""

        return f"{self.started_at:%Y-%m-%d %H:%M:%S} · {self.scenario_name}"

    @classmethod
    def demo_records(cls) -> tuple[ReplayResult, ...]:
        """Return several UI-only records for exercising date-based history selection."""

        latest = cls.demo()
        return (
            latest,
            replace(
                latest,
                started_at=datetime(2026, 8, 2, 9, 18, 5),
                finished_at=datetime(2026, 8, 2, 9, 21, 41),
                duration_s=216.0,
                status="已完成",
                end_status="正常结束",
            ),
            replace(
                latest,
                started_at=datetime(2026, 8, 1, 18, 42, 11),
                finished_at=datetime(2026, 8, 1, 18, 45, 2),
                duration_s=171.0,
                status="失败",
                end_status="异常终止",
            ),
            replace(
                latest,
                started_at=datetime(2026, 8, 1, 9, 0, 0),
                finished_at=datetime(2026, 8, 1, 9, 3, 14),
                duration_s=194.0,
                status="已完成",
                end_status="正常结束",
            ),
            replace(
                latest,
                started_at=datetime(2026, 7, 31, 18, 45, 12),
                finished_at=datetime(2026, 7, 31, 18, 48, 29),
                duration_s=197.0,
                status="已完成",
                end_status="正常结束",
            ),
        )

    @classmethod
    def demo(cls) -> ReplayResult:
        """Return a clearly scoped result fixture for UI development."""

        return cls(
            experiment_id=None,
            scenario_id=UUID("00000000-0000-0000-0000-000000000042"),
            map_id="town04-carla-0.9.16-sumo-1.27.1-v1",
            scenario_name="Town04 混合智驾障碍物场景",
            map_name="Town04",
            seed=42,
            description="混合智驾车辆在 Town04 障碍物场景中的通行表现。",
            started_at=datetime(2026, 8, 3, 13, 4, 12),
            finished_at=datetime(2026, 8, 3, 13, 7, 48),
            duration_s=216.0,
            status="已完成",
            end_status="正常结束",
            data_source="Snapshot + Delta 回放记录",
            metrics=(
                ReplayMetric("车辆总数", "2457", ""),
                ReplayMetric("完成行程车辆数", "2318", ""),
                ReplayMetric("平均速度", "68.5", "km/h"),
                ReplayMetric("平均行程时间", "14.8", "min"),
                ReplayMetric("平均等待时间", "36.2", "s"),
                ReplayMetric("平均排队长度", "8.6", "veh"),
                ReplayMetric("最大排队长度", "24", "veh"),
            ),
            trend_labels=("00:00", "00:36", "01:12", "01:48", "02:24", "03:00"),
            trend_series=(
                ReplayTrendSeries(
                    "车辆数量变化",
                    (12.0, 28.0, 46.0, 58.0, 66.0, 72.0),
                    "#6c8cff",
                    "辆",
                ),
                ReplayTrendSeries(
                    "平均速度变化",
                    (42.0, 39.5, 35.2, 30.4, 29.8, 31.8),
                    "#22d3ee",
                    "km/h",
                ),
                ReplayTrendSeries(
                    "排队车辆数变化",
                    (1.0, 4.0, 9.0, 14.0, 12.0, 7.0),
                    "#f3b6a0",
                    "辆",
                ),
                ReplayTrendSeries(
                    "平均等待时间变化",
                    (3.0, 6.4, 12.0, 18.2, 17.1, 14.7),
                    "#f59e0b",
                    "s",
                ),
            ),
            road_results=(
                ReplayRoadResult("270", 13.2, "畅通", 410.0, 1.0),
                ReplayRoadResult("271", 7.4, "缓行", 680.0, 8.0),
                ReplayRoadResult("272", 3.1, "拥堵", 520.0, 22.0),
                ReplayRoadResult("273", 10.8, "畅通", 360.0, 2.0),
            ),
        )
