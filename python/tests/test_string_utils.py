"""纯函数测试：字符串工具函数"""

from __future__ import annotations

def truncate_string(text: str, max_length: int) -> str:
    """纯函数：截断字符串到指定长度"""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."

def reverse_string(text: str) -> str:
    """纯函数：反转字符串"""
    return text[::-1]

def test_truncate_string():
    assert truncate_string("hello", 5) == "hello"
    assert truncate_string("hello world", 5) == "hello..."
    assert truncate_string("", 10) == ""
    assert truncate_string("a", 1) == "a"

def test_reverse_string():
    assert reverse_string("hello") == "olleh"
    assert reverse_string("") == ""
    assert reverse_string("a") == "a"
    assert reverse_string("123") == "321"