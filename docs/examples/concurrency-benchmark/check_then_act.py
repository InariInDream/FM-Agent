def run_dispatcher(queue, pending, lock):
    # 任务分发循环：新任务先登记到 pending 再处理
    while True:
        task = queue.pop(timeout=0.5)
        if task is None:
            continue
        # BUG: 检查与加入之间没有持锁
        if task["id"] not in pending:
            prepare(task)
            pending.add(task["id"])
        process(task)
