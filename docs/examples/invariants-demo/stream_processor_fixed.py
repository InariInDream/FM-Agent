"""演示目标（fixed 对照版）：与 buggy 版结构相同的流处理循环。

修复方式：extend 之前先检查剩余容量，空间不足时先 flush 排空 buffer；
单个 batch 本身超过 CAPACITY 时，切成不超过 CAPACITY 的段，逐段 flush 处理。
因此任意时刻 len(buffer) <= CAPACITY 都成立。
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
        # 修复: 并入前先检查剩余容量，不足时先 flush 排空 buffer
        if len(batch) > CAPACITY - len(buffer):
            flush(buffer, sink)
        # 修复: 单个超大 batch 切成不超过 CAPACITY 的段，逐段处理，
        # 避免 extend 后瞬时超限
        while len(batch) > CAPACITY:
            chunk, batch = batch[:CAPACITY], batch[CAPACITY:]
            buffer.extend(chunk)
            flush(buffer, sink)
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
