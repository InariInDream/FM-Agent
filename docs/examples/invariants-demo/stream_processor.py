"""演示目标（buggy 版）：不终止的流处理循环。

不变式：任意时刻 len(buffer) <= CAPACITY。
本版本的 bug：收到 batch 后未检查剩余容量就整体并入 buffer，
突发流量下 buffer 中的未处理元素数会瞬时超过 CAPACITY。
"""
CAPACITY = 8


def run_stream_processor(source, sink, metrics):
    # buffer: 待处理元素队列；spec 要求 len(buffer) 永不超过容量上限
    buffer = []
    processed = 0
    dropped = 0
    while True:
        metrics.heartbeat()
        batch = source.poll(timeout=0.5)
        if batch is None:
            continue
        # BUG: 未检查剩余容量就把整个 batch 并入 buffer，
        # 突发 batch 会让未处理元素数瞬时超过容量上限，
        # 在后面逐条 pop 之前的窗口期内不变式被违反
        buffer.extend(batch)
        metrics.gauge("buffer_len", len(buffer))
        if source.shutdown_requested():
            break
        while buffer:
            item = buffer.pop(0)
            if item.get("type") == "heartbeat":
                continue
            try:
                result = transform(item)
            except ValueError:
                dropped += 1
                continue
            sink.emit(result)
            processed += 1
        metrics.counter("processed", processed)
    # 仅在 shutdown 时走到这里：排空 buffer 后隐式返回（永不显式 return）
    flush(buffer, sink)
