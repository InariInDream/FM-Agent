def transfer(src, dst, lock_a, lock_b, amount):
    # 双向转账：amount 为正从 src 转 dst，为负则反向
    if amount >= 0:
        with lock_a:
            with lock_b:
                src.withdraw(amount)
                dst.deposit(amount)
    else:
        # BUG: 反向路径先 B 后 A，与正向路径形成 ABBA 死锁
        with lock_b:
            with lock_a:
                dst.withdraw(-amount)
                src.deposit(-amount)
