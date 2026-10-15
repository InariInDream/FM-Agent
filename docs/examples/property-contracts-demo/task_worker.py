"""演示目标（buggy 版）：不终止的任务处理循环。

spec 里声明的两类约定：
- resources: 每次迭代从 pool 获取的缓冲区在该迭代内释放或移交有界 cache；
  cache 条目数任意时刻不超过 MAX_CACHE = 64，不跨迭代无界增长。
- ordering: 任何路径上 lock_a 先于 lock_b 获取。

本版本的 bug：
1. slow 路径先 lock_b 后 lock_a，顺序相反（与其他线程形成 ABBA 死锁的风险）；
2. fast 路径把缓冲区移交 cache，但 cache 从不淘汰旧条目，跨迭代无界增长
   （缓冲区内存随运行时间持续累积，即泄漏）。
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
            with lock_a:
                with lock_b:
                    # BUG: cache 从不淘汰，条目数跨迭代无界增长
                    cache[task["id"]] = buf
        else:
            # BUG: 获取顺序相反（先 B 后 A），违反 ordering 约定
            with lock_b:
                with lock_a:
                    record(aggregate(cache))
            pool.release(buf)
