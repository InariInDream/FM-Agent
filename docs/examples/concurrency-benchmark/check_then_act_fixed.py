def run_dispatcher(queue, pending, lock):
    # 任务分发循环：新任务先登记到 pending 再处理
    while True:
        task = queue.pop(timeout=0.5)
        if task is None:
            continue
        # 修复: 检查与加入放进同一次持锁内，中途不释放
        with lock:
            if task["id"] not in pending:
                prepare(task)
                pending.add(task["id"])
        process(task)
