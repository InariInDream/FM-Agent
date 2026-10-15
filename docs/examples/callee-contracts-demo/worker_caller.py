"""演示目标（buggy 版）：不终止的任务处理循环，调用 lease_buffer 获取缓冲区。

spec 里声明的约定：
- 本函数 resources：每次迭代从 pool 获取的缓冲区，在该迭代内归还 pool，不跨迭代持有。

callee（lease_buffer）的 resources 约定：返回的缓冲区由调用方在同一迭代内
pool.release() 释放。该约定写在 lease_buffer 的 spec 里，只有随 info 传给
caller 的检查时，caller 这边的违规行为才能被查出来。

本版本的 bug：每轮迭代调用 lease_buffer 拿到 buf，用完直接进下一轮，
从不 pool.release(buf)，缓冲区随运行时间持续漏掉（pool 最终耗尽）。
"""


def run_worker(queue, pool):
    while True:
        task = queue.pop(timeout=0.5)
        if task is None:
            continue
        buf = lease_buffer(pool)
        fill(buf, task)
        if task["prio"] == "fast":
            stats.record_fast(task["id"])
        else:
            stats.record_slow(task["id"])
        # BUG: buf 用完没有归还 pool，下一轮又 lease 一个新的
