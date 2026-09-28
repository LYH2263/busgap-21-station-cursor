"""Bus bunching: planned headway vs actual arrival gaps.

同站按到站时刻排队、相邻两班比间隔。一份站序游标推进同时产出两样东西：
- 相邻两班的串车 / 大间隔 / 正常事件；
- 连续占用（相邻间隔低于串车阈）合并出的忙碌到站段。
事件列表与忙段来自同一次推进，不得先跑完事件再另做一遍合并。
"""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from datetime import datetime

@dataclass
class GapEvent:
    stop_name: str
    earlier_trip: str
    later_trip: str
    gap_min: float
    planned_headway_min: float
    status: str
    suggestion: str

@dataclass
class BusySpan:
    """连续占用的忙碌到站段：[start_at, end_at] 内各班次串成一队。"""
    stop_name: str
    start_at: datetime
    end_at: datetime
    trip_nos: list[str] = field(default_factory=list)

@dataclass
class StopScan:
    stop_name: str
    events: list[GapEvent] = field(default_factory=list)
    busy_spans: list[BusySpan] = field(default_factory=list)
    earliest_at: datetime | None = None

def classify_gap(gap_min: float, planned_headway_min: float, bunch_threshold: float, large_threshold: float) -> tuple[str, str]:
    if gap_min < bunch_threshold:
        return ("bunching", f"间隔 {gap_min:.1f} 分钟低于串车阈值 {bunch_threshold}，建议后车缓行或抽稀。")
    if gap_min > large_threshold:
        return ("large_gap", f"间隔 {gap_min:.1f} 分钟超过大间隔阈值 {large_threshold}，建议前车减速或加发。")
    return ("normal", f"间隔接近计划 {planned_headway_min:.1f} 分钟，保持即可。")

def scan_stop(stop_name: str, items: list[dict], planned_headway_min: float,
              bunch_threshold: float, large_threshold: float) -> StopScan:
    """站序游标推进：沿到站时刻往前走，一对相邻班即写一个事件，
    同一步里把连续占用并入当前忙碌段，间隔拉开（>= 串车阈）立即收口。"""
    items = sorted(items, key=lambda x: x["actual_arrive"])
    scan = StopScan(stop_name)
    if not items:
        return scan
    scan.earliest_at = items[0]["actual_arrive"]
    span_start = span_end = items[0]["actual_arrive"]
    span_trips = [items[0]["trip_no"]]

    def close_span() -> None:
        if len(span_trips) >= 2:  # 单车次不构成连续占用段
            scan.busy_spans.append(BusySpan(stop_name, span_start, span_end, list(span_trips)))

    for i in range(1, len(items)):
        prev, cur = items[i - 1], items[i]
        gap_min = (cur["actual_arrive"] - prev["actual_arrive"]).total_seconds() / 60.0
        status, suggestion = classify_gap(gap_min, planned_headway_min, bunch_threshold, large_threshold)
        scan.events.append(GapEvent(stop_name, prev["trip_no"], cur["trip_no"],
                                    round(gap_min, 2), planned_headway_min, status, suggestion))
        if gap_min < bunch_threshold:
            # 连续占用：忙段游标延伸到当前班次
            span_end = cur["actual_arrive"]
            span_trips.append(cur["trip_no"])
        else:
            # 间隔拉开（含等于串车阈的边界）：先收口前一忙段，再从本班重新起段
            close_span()
            span_start = span_end = cur["actual_arrive"]
            span_trips = [cur["trip_no"]]
    close_span()
    return scan

def scan_arrivals(arrivals: list[dict], planned_headway_min: float, bunch_threshold: float,
                  large_threshold: float) -> tuple[list[StopScan], list[GapEvent], list[BusySpan], datetime | None]:
    by_stop: dict[str, list[dict]] = {}
    for a in arrivals:
        by_stop.setdefault(a["stop_name"], []).append(a)
    scans = [scan_stop(stop, items, planned_headway_min, bunch_threshold, large_threshold)
             for stop, items in by_stop.items()]
    events = [e for s in scans for e in s.events]
    busy_spans = [sp for s in scans for sp in s.busy_spans]
    earliest = min((s.earliest_at for s in scans if s.earliest_at is not None), default=None)
    return scans, events, busy_spans, earliest

def detect_bunching(arrivals: list[dict], planned_headway_min: float, bunch_threshold: float, large_threshold: float) -> list[GapEvent]:
    _, events, _, _ = scan_arrivals(arrivals, planned_headway_min, bunch_threshold, large_threshold)
    return events

def events_to_dicts(events: list[GapEvent]) -> list[dict]:
    return [asdict(e) for e in events]

def busy_spans_to_dicts(busy_spans: list[BusySpan]) -> list[dict]:
    return [{"stop_name": sp.stop_name, "start_at": sp.start_at.isoformat(),
             "end_at": sp.end_at.isoformat(), "trip_nos": list(sp.trip_nos)} for sp in busy_spans]
