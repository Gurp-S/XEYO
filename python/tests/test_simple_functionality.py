"""简单的功能测试 - 验证基础工具和功能"""

import pytest

from tools.catalog import build_default_registry
from msgtypes.message import user_message
from engine.query_loop import query_loop
from engine.abort import AbortController
from engine.budget import BudgetTracker
from model.chunks import ModelChunk


class SimpleTestModel:
    """简单的测试模型，模拟基本响应"""
    
    def __init__(self, response_text="Test response"):
        self.response_text = response_text
        self.turns = 0
    
    async def stream(self, messages, tools, abort):
        
        abort.raise_if_aborted()
        self.turns += 1
        
        if self.turns == 1:
            yield ModelChunk(kind="text_delta", text=self.response_text)


@pytest.fixture
def registry(tmp_path):
    """创建测试用的工具注册表"""
    return build_default_registry(cwd=str(tmp_path))


def test_basic_tool_availability(registry):
    """测试基本工具是否可用"""
    schema_names = [s.get("name") for s in registry.schemas()]
    
    # 检查关键工具是否存在
    assert "Glob" in schema_names
    assert "Read" in schema_names
    assert "Write" in schema_names
    assert "Edit" in schema_names


def test_user_message_creation():
    """测试用户消息创建"""
    msg = user_message("测试消息")
    assert msg["role"] == "user"
    assert msg["content"] == "测试消息"


def test_abort_controller():
    """测试中止控制器"""
    abort = AbortController()
    
    # 初始状态应该不是中止
    assert not abort.is_aborted()
    
    # 测试中止功能
    abort.abort()
    assert abort.is_aborted()
    
    # 测试异常抛出
    abort.raise_if_aborted()


def test_budget_tracker():
    """测试预算跟踪器"""
    budget = BudgetTracker(
        max_turns=5,
        max_tool_calling=10,
        usd_limit=1.0,
        provider="test",
        model="test"
    )
    
    assert budget.max_turns == 5
    assert budget.max_tool_calling == 10
    assert budget.usd_limit == 1.0


@pytest.mark.asyncio
async def test_simple_query_loop(registry, tmp_path):
    """测试简单的查询循环"""
    # 创建临时文件用于测试
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello, World!")
    
    # 创建测试模型
    model = SimpleTestModel("文件已读取")
    
    # 创建消息存储
    store = [user_message(f"读取文件 {test_file.name}")]
    
    events = []
    async for event in query_loop(
        store=store,
        model=model,
        tools=registry,
        prompt=None,
        system_prompt="测试系统提示",
        abort=AbortController(),
        budget=BudgetTracker(
            max_turns=3,
            max_tool_calling=5,
            usd_limit=None,
            provider="test",
            model="test"
        ),
        multi_agent=False
    ):
        events.append(event)
    
    # 验证事件
    assert len(events) > 0
    text_events = [e for e in events if hasattr(e, 'text')]
    assert len(text_events) > 0


def test_file_operations(registry, tmp_path):
    """测试文件操作工具"""
    test_file = tmp_path / "write_test.txt"
    test_content = "这是一个测试文件"
    
    # 测试Write工具
    write_tool = registry.get_tool("Write")
    assert write_tool is not None
    
    # 测试Read工具
    read_tool = registry.get_tool("Read")
    assert read_tool is not None
    
    # 创建文件
    write_tool.tool_func(
        file_path=str(test_file),
        content=test_content
    )
    
    # 验证文件创建
    assert test_file.exists()
    assert test_file.read_text() == test_content
    
    # 读取文件
    result = read_tool.tool_func(file_path=str(test_file))
    assert result == test_content


def test_glob_tool(registry, tmp_path):
    """测试Glob工具"""
    # 创建测试文件
    (tmp_path / "test1.txt").write_text("文件1")
    (tmp_path / "test2.txt").write_text("文件2")
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "test3.txt").write_text("文件3")
    
    glob_tool = registry.get_tool("Glob")
    assert glob_tool is not None
    
    # 测试glob模式
    result = glob_tool.tool_func(pattern="*.txt")
    assert len(result) >= 2  # 应该找到至少2个.txt文件
    
    result = glob_tool.tool_func(pattern="**/*.txt")
    assert len(result) >= 3  # 应该找到至少3个.txt文件（包括子目录）


def test_error_handling():
    """测试错误处理"""
    from tools.agent_tool.agent_tool import AgentTool
    
    # 测试无效输入
    with pytest.raises(Exception):
        AgentTool().tool_func()  # 缺少必需参数


if __name__ == "__main__":
    pytest.main([__file__, "-v"])