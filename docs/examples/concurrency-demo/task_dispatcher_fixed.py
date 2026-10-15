"""演示目标（fixed 版）：不终止的任务分发循环，会被多个线程用同一组
pending/stats/lock 并发调用。

spec 里声明的 concurrency 约定：pending 的"检查再加入"序列必须在同一次
持锁内完成；stats 的所有读写必须持有 lock。

本版本的修复：
1. pending 的检查与加入整段放进同一次 with lock 内，中途不释放，
   check-then-act 变成原子操作；
2. stats["done"] += 1 也放进 with lock 内，自增的读-改-写不再交错。
"""


def run_dispatcher(queue, pending, stats, lock):
    while True:
        task = queue.pop(timeout=0.5)
        if task is None:
            continue
        # 修复: 检查与加入在同一次持锁内完成
        with lock:
            if task["id"] not in pending:
                prepare(task)
                pending.add(task["id"])
        process(task)
        # 修复: 共享计数器自增持锁
        with lock:
            stats["done"] += 1
