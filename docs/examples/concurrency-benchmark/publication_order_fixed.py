def publish(config, ready_flag):
    # 配置发布：重载数据并通知等待的读者线程
    snapshot = config.prepare()
    if snapshot is None:
        snapshot = config.defaults()
    # 修复: 先完成 config 的全部写入，最后才置 ready_flag
    config.reload()
    config.apply(snapshot)
    log("config published")
    ready_flag.set()
