"""Production file tools for eval actors; grading remains outside execution."""
from copy import deepcopy
from pathlib import Path

from tools.base_tool import ToolResult
from tools.fileio.read_state import ReadFileState
from tools.fileio.paths import expand_path
from tools.file_read_tool.file_read_tool import FileReadTool
from tools.file_write_tool.file_write_tool import FileWriteTool
from tools.grep_tool.grep_tool import GrepTool
from tools.tool_registry import ToolRegistry


class NativeTaskFiles:
    def __init__(self, workspace, artifact_root):
        self.workspace = Path(workspace).resolve()
        self.root = Path(artifact_root).resolve()
        if not self.root.is_relative_to(self.workspace):
            raise ValueError('artifact_root_outside_workspace')
        self.root.mkdir(parents=True, exist_ok=True)
        self.attempts = []
        state = ReadFileState()
        self.registry = ToolRegistry(cwd=str(self.workspace))
        for tool in (FileReadTool(cwd=str(self.workspace), read_state=state),
                     FileWriteTool(cwd=str(self.workspace), read_state=state),
                     GrepTool(cwd=str(self.workspace))):
            self.registry.register(tool)

    def schemas(self):
        return [self.registry.get(name).schema() for name in ('Read', 'Grep', 'Write')]

    def refers_to_artifacts(self, name):
        """Produced answers are not independent historical evidence."""
        return bool(isinstance(name, str) and name and
            Path(expand_path(name, cwd=str(self.workspace))).resolve().is_relative_to(self.root))

    def call(self, _arguments):
        # The reused actor has a legacy ArtifactWrite dispatch branch. Old
        # transcript calls remain history, not an enabled write capability.
        raise ValueError('unknown_tool: ArtifactWrite')

    async def execute(self, use, abort):
        if use.name == 'Write':
            # Store resolved attempts for the existing artifact grader, while
            # the actor retains the actual, unmodified model call and receipt.
            args = deepcopy(use.input)
            if isinstance(args, dict) and isinstance(args.get('file_path'), str):
                path = Path(expand_path(args['file_path'], cwd=str(self.workspace))).resolve()
                args['file_path'] = str(path)
                self.attempts.append(args)
                if not path.is_relative_to(self.root) or path == self.root:
                    return ToolResult('Permission denied: outside artifact_root', is_error=True,
                                      error_kind='PERMISSION_DENIED')
            else:
                self.attempts.append(args)
        return await self.registry.run(use, abort)
