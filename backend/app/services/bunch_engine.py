"""Bus bunching: planned headway vs actual arrival gaps.

站点到站序游标：游标沿同一站点的到站时刻向前推进，一次推进同时产出两类结果——
1. 相邻两班的间隔事件（串车 / 大间隔 / 正常）；
2. 连续被异常相邻对（串车或大间隔）占用的到站合并成的忙碌到站段。
事件列表与忙段必须来自同一次游标推进，不能先跑完事件再另写一段合并。
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
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
    """连续异常相邻对覆盖的到站段：[start_arrive, end_arrive]。"""
    stop_name: str
    start_trip: str
    end_trip: str
    start_arrive: datetime
    end_arrive: datetime
    kinds: str  # 段内出现过的异常状态，逗号连接，如 "bunching,large_gap"

def classify_gap(gap_min: float, planned_headway_min: float, bunch_threshold: float, large_threshold: float) -> tuple[str, str]:
    if gap_min < bunch_threshold:
        return ("bunching", f"间隔 {gap_min:.1f} 分钟低于串车阈值 {bunch_threshold}，建议后车缓行或抽稀。")
    if gap_min > large_threshold:
        return ("large_gap", f"间隔 {gap_min:.1f} 分钟超过大间隔阈值 {large_threshold}，建议前车减速或加发。")
    return ("normal", f"间隔接近计划 {planned_headway_min:.1f} 分钟，保持即可。")

def analyze_bunching(arrivals: list[dict], planned_headway_min: float, bunch_threshold: float, large_threshold: float) -> tuple[list[GapEvent], list[BusySpan]]:
    by_stop: dict[str, list[dict]] = {}
    for a in arrivals:
        by_stop.setdefault(a["stop_name"], []).append(a)
    events: list[GapEvent] = []
    busy_spans: list[BusySpan] = []
    for stop, items in by_stop.items():
        stop_events, stop_spans = _advance_stop_cursor(
            stop, sorted(items, key=lambda x: x["actual_arrive"]),
            planned_headway_min, bunch_threshold, large_threshold)
        events.extend(stop_events)
        busy_spans.extend(stop_spans)
    return events, busy_spans

def _advance_stop_cursor(stop_name: str, items: list[dict], planned_headway_min: float,
                         bunch_threshold: float, large_threshold: float) -> tuple[list[GapEvent], list[BusySpan]]:
    """站序游标推进：每跨过一对相邻到站，当即写出间隔事件；
    若该对异常（串车/大间隔），同步扩展当前忙碌到站段，正常对则收段。
    事件与忙段在同一个循环里产生。"""
    events: list[GapEvent] = []
    busy_spans: list[BusySpan] = []
    if len(items) < 2:
        return events, busy_spans

    span: BusySpan | None = None

    def flush() -> None:
        nonlocal span
        if span is not None:
            busy_spans.append(span)
            span = None

    for i in range(1, len(items)):
        prev, cur = items[i - 1], items[i]
        gap_min = (cur["actual_arrive"] - prev["actual_arrive"]).total_seconds() / 60.0
        status, suggestion = classify_gap(gap_min, planned_headway_min, bunch_threshold, large_threshold)
        # 同一次推进：写事件
        events.append(GapEvent(stop_name, prev["trip_no"], cur["trip_no"], round(gap_min, 2),
                               planned_headway_min, status, suggestion))
        # 同一次推进：维护连续占用的忙段
        if status in ("bunching", "large_gap"):
            if span is None:
                span = BusySpan(stop_name, prev["trip_no"], cur["trip_no"],
                                prev["actual_arrive"], cur["actual_arrive"], status)
            else:
                # 与上一异常对相邻（共享 prev 到站），并入同一段
                span.end_trip = cur["trip_no"]
                span.end_arrive = cur["actual_arrive"]
                if status not in span.kinds.split(","):
                    span.kinds = f"{span.kinds},{status}"
        else:
            flush()
    flush()
    return events, busy_spans

def detect_bunching(arrivals: list[dict], planned_headway_min: float, bunch_threshold: float, large_threshold: float) -> list[GapEvent]:
    events, _ = analyze_bunching(arrivals, planned_headway_min, bunch_threshold, large_threshold)
    return events

def events_to_dicts(events: list[GapEvent]) -> list[dict]:
    return [asdict(e) for e in events]

def spans_to_dicts(spans: list[BusySpan]) -> list[dict]:
    return [{"stop_name": s.stop_name, "start_trip": s.start_trip, "end_trip": s.end_trip,
             "start_arrive": s.start_arrive.isoformat(), "end_arrive": s.end_arrive.isoformat(),
             "kinds": s.kinds} for s in spans]
