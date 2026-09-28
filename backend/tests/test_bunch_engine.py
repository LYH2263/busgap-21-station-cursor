from datetime import datetime, timedelta
from app.services.bunch_engine import classify_gap, detect_bunching, scan_arrivals

PLANNED = 8.0
BUNCH = 3.0
LARGE = 15.0

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

# ---- 夹具一：阈值边界（等于阈 / 小一分钟 / 大一分钟）----
def test_fixture_threshold_boundary():
    base = datetime(2026, 9, 17, 7, 0)
    # 相邻间隔依次：3(=串车阈)、2(小1分)、14、15(=大间隔阈)、16(大1分)
    gaps = [0, 3, 5, 19, 34, 50]
    arrivals = [{"stop_name": "S", "trip_no": f"T{i}",
                 "actual_arrive": base + timedelta(minutes=g)} for i, g in enumerate(gaps)]
    scans, events, busy_spans, earliest = scan_arrivals(arrivals, PLANNED, BUNCH, LARGE)
    assert [e.status for e in events] == ["normal", "bunching", "normal", "normal", "large_gap"]
    assert len(events) == 5
    # 只有 2 分钟那对（T1 07:03 → T2 07:05）连续占用；等于串车阈的 3 分钟不并段
    assert len(busy_spans) == 1
    span = busy_spans[0]
    assert span.start_at == base + timedelta(minutes=3)
    assert span.end_at == base + timedelta(minutes=5)
    assert span.trip_nos == ["T1", "T2"]
    assert earliest == base

# ---- 夹具二：两班时刻交叉（输入未按时刻/站点排序，游标需自行排队）----
def test_fixture_crossing_arrival_order():
    base = datetime(2026, 9, 17, 7, 0)
    arrivals = [
        {"stop_name": "Y", "trip_no": "T3", "actual_arrive": base + timedelta(minutes=12)},
        {"stop_name": "X", "trip_no": "T3", "actual_arrive": base + timedelta(minutes=20)},
        {"stop_name": "X", "trip_no": "T1", "actual_arrive": base + timedelta(minutes=0)},
        {"stop_name": "Y", "trip_no": "T1", "actual_arrive": base + timedelta(minutes=0)},
        {"stop_name": "Y", "trip_no": "T2", "actual_arrive": base + timedelta(minutes=10)},
        {"stop_name": "X", "trip_no": "T2", "actual_arrive": base + timedelta(minutes=2)},
    ]
    scans, events, busy_spans, earliest = scan_arrivals(arrivals, PLANNED, BUNCH, LARGE)
    by_stop = {s.stop_name: s for s in scans}
    # X：T1→T2 间隔 2 串车，T2→T3 间隔 18 大间隔
    assert [e.status for e in by_stop["X"].events] == ["bunching", "large_gap"]
    # Y：T1→T2 间隔 10 正常，T2→T3 间隔 2 串车
    assert [e.status for e in by_stop["Y"].events] == ["normal", "bunching"]
    assert len(events) == 4
    # 两个忙段分属不同站、不跨站合并（聚合顺序不做承诺，按站名排序比较）
    assert sorted((sp.stop_name, tuple(sp.trip_nos)) for sp in busy_spans) == [
        ("X", ("T1", "T2")), ("Y", ("T2", "T3")),
    ]
    x_span, y_span = by_stop["X"].busy_spans[0], by_stop["Y"].busy_spans[0]
    assert (x_span.start_at, x_span.end_at) == (base, base + timedelta(minutes=2))
    assert (y_span.start_at, y_span.end_at) == (base + timedelta(minutes=10), base + timedelta(minutes=12))
    assert earliest == base

# ---- 夹具三：中间插入班（相邻两对都要进事件，忙段合并但不吞掉中间对）----
def test_fixture_middle_insertion():
    base = datetime(2026, 9, 17, 7, 0)
    # 输入按 T1、T3、T2 乱序给入，T2 是插进首尾之间的班次
    arrivals = [
        {"stop_name": "S", "trip_no": "T1", "actual_arrive": base + timedelta(minutes=0)},
        {"stop_name": "S", "trip_no": "T3", "actual_arrive": base + timedelta(minutes=4)},
        {"stop_name": "S", "trip_no": "T2", "actual_arrive": base + timedelta(minutes=2)},
    ]
    scans, events, busy_spans, earliest = scan_arrivals(arrivals, PLANNED, BUNCH, LARGE)
    assert len(events) == 2
    assert [(e.earlier_trip, e.later_trip, e.status) for e in events] == [
        ("T1", "T2", "bunching"), ("T2", "T3", "bunching"),
    ]
    # 连续占用合并为一个外层忙段，但内部相邻两一对都没丢
    assert len(busy_spans) == 1
    span = busy_spans[0]
    assert span.start_at == base
    assert span.end_at == base + timedelta(minutes=4)
    assert span.trip_nos == ["T1", "T2", "T3"]
    assert earliest == base
