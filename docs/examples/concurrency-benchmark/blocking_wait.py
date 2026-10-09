def on_timer(client, results):
    # 定时器回调：异步发起请求，等结果追加到 results
    # 注意：本回调运行在唯一的执行器线程上
    future = client.call_async(make_request())
    # BUG: 在唯一的执行器线程上原地等待，而 future 的完成回调也需要这个线程
    while not future.done():
        sleep(0.01)
    result = future.result()
    results.append(result)
    log_result(result)
