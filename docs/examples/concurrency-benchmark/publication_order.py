def publish(config, ready_flag):
    # 配置发布：重载数据并通知等待的读者线程
    snapshot = config.prepare()
    if snapshot is None:
        snapshot = config.defaults()
    # BUG: 先置就绪标志再写数据，读者线程看到标志时数据还没写好
    ready_flag.set()
    config.reload()
    config.apply(snapshot)
    log("config published")
