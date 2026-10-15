def transfer(src, dst, lock_a, lock_b, amount):
    # 双向转账：amount 为正从 src 转 dst，为负则反向
    if amount >= 0:
        with lock_a:
            with lock_b:
                src.withdraw(amount)
                dst.deposit(amount)
    else:
        # 修复: 反向路径也先 A 后 B，两条路径锁顺序一致
        with lock_a:
            with lock_b:
                dst.withdraw(-amount)
                src.deposit(-amount)
