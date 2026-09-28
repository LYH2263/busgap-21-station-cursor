from datetime import datetime, timedelta
from app.services.bunch_engine import analyze_bunching, classify_gap, detect_bunching

BUNCH, LARGE, PLANNED = 3.0, 15.0, 8.0

def test_classify_bunching():
    assert classify_gap(2.0, 8.0, 3.0, 15.0)[0] == "bunching"

def test_classify_large():
    assert classify_gap(16.0, 8.0, 3.0, 15.0)[0] == "large_gap"

def test_classify_normal():
    assert classify_gap(8.0, 8.0, 3.0, 15.0)[0] == "normal"

def test_detect_bunching_events():
    base = datetime(2026, 1, 1, 8, 0)
    arrivals = [
        {"stop_name": "A", "trip_no": "T1", "actual_arrive": base},
        {"stop_name": "A", "trip_no": "T2", "actual_arrive": base + timedelta(minutes=2)},
        {"stop_name": "A", "trip_no": "T3", "actual_arrive": base + timedelta(minutes=20)},
    ]
    events = detect_bunching(arrivals, 8.0, 3.0, 15.0)
    assert len(events) == 2
    assert events[0].status == "bunching"
    assert events[1].status == "large_gap"

def _stop_arrivals(stop: str, trip_specs: list[tuple[str, datetime]]) -> list[dict]:
    return [{"stop_name": stop, "trip_no": t, "actual_arrive": ts} for t, ts in trip_specs]

# 夹具一：阈边界——等于阈不报警；比阈小一分钟串车；比阈大一分钟大间隔
def test_threshold_boundaries():
    base = datetime(2026, 1, 1, 8, 0)
    # 相邻间隔依次：2（比串车阈小1分钟）、3（等于串车阈）、15（等于大间隔阈）、16（比大间隔阈大1分钟）
    offsets = [0, 2, 5, 20, 36]
    arrivals = _stop_arrivals("阈边界站", [(f"T{i}", base + timedelta(minutes=m)) for i, m in enumerate(offsets)])
    events, spans = analyze_bunching(arrivals, PLANNED, BUNCH, LARGE)

    assert [e.status for e in events] == ["bunching", "normal", "normal", "large_gap"]
    assert len(events) == 4
    assert classify_gap(BUNCH, PLANNED, BUNCH, LARGE)[0] == "normal"
    assert classify_gap(LARGE, PLANNED, BUNCH, LARGE)[0] == "normal"

    # 串车对与大间隔对被两对正常对隔开，收成两个独立忙段
    assert len(spans) == 2
    assert (spans[0].start_trip, spans[0].end_trip) == ("T0", "T1")
    assert spans[0].start_arrive == base + timedelta(minutes=0)
    assert spans[0].end_arrive == base + timedelta(minutes=2)
    assert spans[0].kinds == "bunching"
    assert (spans[1].start_trip, spans[1].end_trip) == ("T3", "T4")
    assert spans[1].start_arrive == base + timedelta(minutes=20)
    assert spans[1].end_arrive == base + timedelta(minutes=36)
    assert spans[1].kinds == "large_gap"

    # 时间轴最早点（reports.timeline 的 t0）：游标排队后第一个到站
    earliest = min(a["actual_arrive"] for a in arrivals)
    assert earliest == base

# 夹具二：两班时刻交叉——实际到站次序与班次编号/录入次序相反，按到站时刻排队
def test_crossing_arrivals_ordered_by_time():
    base = datetime(2026, 1, 1, 8, 0)
    # 先给 T1（后到），再给 T2（先到）：游标必须按实际时刻重排
    arrivals = _stop_arrivals("交叉站", [
        ("T1", base + timedelta(minutes=10)),
        ("T2", base + timedelta(minutes=8)),
    ])
    events, spans = analyze_bunching(arrivals, PLANNED, BUNCH, LARGE)

    assert len(events) == 1
    assert events[0].status == "bunching"
    assert events[0].earlier_trip == "T2"
    assert events[0].later_trip == "T1"
    assert events[0].gap_min == 2.0

    assert len(spans) == 1
    assert spans[0].start_trip == "T2"
    assert spans[0].end_trip == "T1"
    assert spans[0].start_arrive == base + timedelta(minutes=8)
    assert spans[0].end_arrive == base + timedelta(minutes=10)

    earliest = min(a["actual_arrive"] for a in arrivals)
    assert earliest == base + timedelta(minutes=8)

# 夹具三：中间插入一班——相邻两对都要进事件，不能只剩首尾一对；忙段连续占用三到站
def test_inserted_middle_trip_both_pairs_emit():
    base = datetime(2026, 1, 1, 8, 0)
    # T2 插在 T1、T3 之间：T1->T2 间隔 2 分钟串车，T2->T3 间隔 18 分钟大间隔
    arrivals = _stop_arrivals("插入站", [
        ("T1", base + timedelta(minutes=0)),
        ("T2", base + timedelta(minutes=2)),
        ("T3", base + timedelta(minutes=20)),
    ])
    events, spans = analyze_bunching(arrivals, PLANNED, BUNCH, LARGE)

    assert len(events) == 2  # 两对都要在，不许被首尾一对吞掉
    assert [(e.earlier_trip, e.later_trip, e.status) for e in events] == [
        ("T1", "T2", "bunching"),
        ("T2", "T3", "large_gap"),
    ]

    # 两对共享中间到站 T2，连续占用于同一次推进，合并为一个忙段 T1->T3
    assert len(spans) == 1
    span = spans[0]
    assert (span.start_trip, span.end_trip) == ("T1", "T3")
    assert span.start_arrive == base
    assert span.end_arrive == base + timedelta(minutes=20)
    assert span.kinds == "bunching,large_gap"

    earliest = min(a["actual_arrive"] for a in arrivals)
    assert earliest == base

# 锁定种子：市民中心串车、火车站大间隔，事件与时间轴点位改完必须和现在一模一样
def test_seed_stops_unchanged():
    base = datetime(2026, 9, 17, 7, 0, 0)
    civic = _stop_arrivals("市民中心", [
        ("T01", base + timedelta(minutes=6)),
        ("T02", base + timedelta(minutes=8)),
        ("T03", base + timedelta(minutes=24)),
        ("T04", base + timedelta(minutes=32)),
    ])
    station = _stop_arrivals("火车站", [
        ("T01", base + timedelta(minutes=12)),
        ("T02", base + timedelta(minutes=14)),
        ("T03", base + timedelta(minutes=30)),
        ("T04", base + timedelta(minutes=38)),
    ])
    events, spans = analyze_bunching(civic + station, PLANNED, BUNCH, LARGE)
    by_stop = {}
    for e in events:
        by_stop.setdefault(e.stop_name, []).append(e)

    assert [e.status for e in by_stop["市民中心"]] == ["bunching", "large_gap", "normal"]
    assert [e.status for e in by_stop["火车站"]] == ["bunching", "large_gap", "normal"]
    assert by_stop["市民中心"][0].gap_min == 2.0
    assert by_stop["市民中心"][1].gap_min == 16.0
    assert by_stop["火车站"][0].gap_min == 2.0
    assert by_stop["火车站"][1].gap_min == 16.0

    # 两站的串车对与大间隔对相邻，各并成一个忙段
    stop_spans = {s.stop_name: s for s in spans}
    assert (stop_spans["市民中心"].start_trip, stop_spans["市民中心"].end_trip) == ("T01", "T03")
    assert stop_spans["市民中心"].start_arrive == base + timedelta(minutes=6)
    assert stop_spans["市民中心"].end_arrive == base + timedelta(minutes=24)
    assert (stop_spans["火车站"].start_trip, stop_spans["火车站"].end_trip) == ("T01", "T03")
    assert stop_spans["火车站"].start_arrive == base + timedelta(minutes=12)
    assert stop_spans["火车站"].end_arrive == base + timedelta(minutes=30)

    # 时间轴最早点（默认看市民中心）保持不变
    civic_sorted = sorted(civic, key=lambda a: a["actual_arrive"])
    assert civic_sorted[0]["trip_no"] == "T01"
    assert civic_sorted[0]["actual_arrive"] == base + timedelta(minutes=6)
