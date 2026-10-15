def on_timer(client, results):
    # 定时器回调：异步发起请求，等结果追加到 results
    # 注意：本回调运行在唯一的执行器线程上
    future = client.call_async(make_request())

    # 修复: 用完成回调收集结果，不原地等待，释放执行器线程
    def _on_done(fut):
        results.append(fut.result())
        log_result(fut.result())

    future.add_done_callback(_on_done)
