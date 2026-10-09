def consumer(queue, cond):
    # 消费者循环：等待队列非空后取出一个任务处理
    while True:
        with cond:
            # BUG: 用 if 而不是 while，虚假唤醒后直接 pop 空队列
            if not queue:
                cond.wait()
            item = queue.pop()
        process(item)
        mark_done(item)
