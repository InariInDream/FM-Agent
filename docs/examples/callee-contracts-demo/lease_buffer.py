"""callee：从缓冲区池取一个缓冲区给调用方用。

它的 spec（见 lease_buffer.spec.json）声明了 resources 约定：
返回的缓冲区由调用方负责在同一轮迭代内 pool.release() 释放。
这个约定管的是调用方的行为，只看 lease_buffer 自己检查不出来。
"""


def lease_buffer(pool):
    buf = pool.acquire()
    buf.clear()
    return buf
