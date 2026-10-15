"""演示目标（fixed 对照版）：与 buggy 版结构相同的任务处理循环。

修复方式：每轮迭代用完 buf 后 pool.release(buf) 归还，
满足本函数的 resources 约定，也满足 callee lease_buffer 对调用方的要求。
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
        # 修复: 用完即归还
        pool.release(buf)
