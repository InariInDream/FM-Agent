def consumer(queue, cond):
    # 消费者循环：等待队列非空后取出一个任务处理
    while True:
        with cond:
            # 修复: 用 while 循环复查条件，虚假唤醒后重新等待
            while not queue:
                cond.wait()
            item = queue.pop()
        process(item)
        mark_done(item)
