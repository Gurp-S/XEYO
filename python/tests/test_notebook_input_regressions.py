import json
import pytest
from engine.abort import AbortController
from tools.notebook_edit_tool import NotebookEditTool


@pytest.mark.asyncio
async def test_create_notebook_has_encoding(tmp_path):
    path = tmp_path / 'new.ipynb'
    result = await NotebookEditTool(cwd=str(tmp_path)).execute(
        {'notebook_path': str(path), 'edit_mode': 'insert', 'new_source': '你好'}, AbortController())
    assert not result.is_error, result.content
    assert json.loads(path.read_text())['cells'][0]['source'] == ['你好']


@pytest.mark.asyncio
async def test_replace_markdown_does_not_publish_code_only_fields(tmp_path):
    path = tmp_path / 'n.ipynb'
    path.write_text(json.dumps({'nbformat': 4, 'nbformat_minor': 5, 'metadata': {}, 'cells': [
        {'cell_type': 'code', 'metadata': {}, 'source': ['x'], 'outputs': [], 'execution_count': 1}]}))
    result = await NotebookEditTool(cwd=str(tmp_path)).execute(
        {'notebook_path': str(path), 'edit_mode': 'replace', 'cell_idx': 0,
         'cell_type': 'markdown', 'new_source': '# hi'}, AbortController())
    assert not result.is_error, result.content
    cell = json.loads(path.read_text())['cells'][0]
    assert 'outputs' not in cell and 'execution_count' not in cell


@pytest.mark.asyncio
async def test_markdown_to_code_removes_attachments(tmp_path):
    path = tmp_path / 'n.ipynb'
    path.write_text(json.dumps({'nbformat': 4, 'nbformat_minor': 5, 'metadata': {}, 'cells': [
        {'cell_type': 'markdown', 'metadata': {}, 'source': ['x'], 'attachments': {'x': {}}}]}))
    result = await NotebookEditTool(cwd=str(tmp_path)).execute(
        {'notebook_path': str(path), 'edit_mode': 'replace', 'cell_idx': 0,
         'cell_type': 'code', 'new_source': 'print(1)'}, AbortController())
    assert not result.is_error, result.content
    cell = json.loads(path.read_text())['cells'][0]
    assert 'attachments' not in cell
    assert cell['outputs'] == [] and cell['execution_count'] is None
