def count_events(stream, stats, lock):
    # 事件统计循环：处理事件并累计已处理数量
    while True:
        ev = stream.poll(timeout=0.5)
        if ev is None:
            continue
        if ev.get("type") == "heartbeat":
            continue
        handle(ev)
        # 修复: 共享计数器自增放进 with lock 内
        with lock:
            stats["count"] += 1
