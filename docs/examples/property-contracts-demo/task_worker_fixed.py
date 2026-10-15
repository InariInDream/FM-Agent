"""演示目标（fixed 对照版）：与 buggy 版结构相同的任务处理循环。

修复方式：
1. 两条路径统一先 lock_a 后 lock_b，满足 ordering 约定；
2. cache 写入前检查容量，达到 MAX_CACHE 时淘汰最旧条目并释放其缓冲区，
   因此 cache 有界、每个缓冲区都有明确归宿，满足 resources 约定。
"""
MAX_CACHE = 64


def run_task_worker(queue, pool, lock_a, lock_b, cache):
    # cache: 已处理任务的缓冲区索引；pool: 缓冲区池
    while True:
        task = queue.pop(timeout=0.5)
        if task is None:
            continue
        buf = pool.acquire()
        fill(buf, task)
        if task["prio"] == "fast":
            # 修复: 统一先 A 后 B
            with lock_a:
                with lock_b:
                    # 修复: 有界，写满时淘汰最旧条目并释放其缓冲区
                    if len(cache) >= MAX_CACHE:
                        old_id = next(iter(cache))
                        pool.release(cache.pop(old_id))
                    cache[task["id"]] = buf
        else:
            # 修复: 同样先 A 后 B
            with lock_a:
                with lock_b:
                    record(aggregate(cache))
            pool.release(buf)
