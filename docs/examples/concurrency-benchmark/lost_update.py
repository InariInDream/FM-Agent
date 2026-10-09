def count_events(stream, stats, lock):
    # 事件统计循环：处理事件并累计已处理数量
    while True:
        ev = stream.poll(timeout=0.5)
        if ev is None:
            continue
        if ev.get("type") == "heartbeat":
            continue
        handle(ev)
        # BUG: 共享计数器自增未持锁
        stats["count"] += 1
