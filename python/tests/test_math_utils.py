"""纯函数测试：数学工具函数"""

from __future__ import annotations

def clamp(value: int, min_val: int, max_val: int) -> int:
    """纯函数：将值限制在指定范围内"""
    return max(min_val, min(max_val, value))

def factorial(n: int) -> int:
    """纯函数：计算阶乘"""
    if n < 0:
        raise ValueError("阶乘只能计算非负整数")
    if n == 0:
        return 1
    result = 1
    for i in range(1, n + 1):
        result *= i
    return result

def test_clamp():
    assert clamp(5, 0, 10) == 5
    assert clamp(-1, 0, 10) == 0
    assert clamp(15, 0, 10) == 10
    assert clamp(5, 5, 5) == 5

def test_factorial():
    assert factorial(0) == 1
    assert factorial(1) == 1
    assert factorial(5) == 120
    assert factorial(3) == 6