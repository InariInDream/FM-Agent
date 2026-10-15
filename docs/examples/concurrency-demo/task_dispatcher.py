"""演示目标（buggy 版）：不终止的任务分发循环，会被多个线程用同一组
pending/stats/lock 并发调用。

spec 里声明的 concurrency 约定：pending 的"检查再加入"序列必须在同一次
持锁内完成；stats 的所有读写必须持有 lock。

本版本的 bug：
1. check-then-act：if task["id"] not in pending 与 pending.add(...) 之间
   没有持锁，两个线程会同时通过检查，同一任务被处理两次；
2. stats["done"] += 1 自增未持锁，并发下丢失更新（读-改-写交错）。
"""


def run_dispatcher(queue, pending, stats, lock):
    while True:
        task = queue.pop(timeout=0.5)
        if task is None:
            continue
        # BUG: 检查与加入之间没有持锁
        if task["id"] not in pending:
            prepare(task)
            pending.add(task["id"])
        process(task)
        # BUG: 共享计数器自增未持锁
        stats["done"] += 1
