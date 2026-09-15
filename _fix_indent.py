import io
def fix(p, a, b):
    s = io.open(p, encoding="utf-8", newline="").read()
    assert s.count(a) == 1, (p, s.count(a))
    io.open(p, "w", encoding="utf-8", newline="").write(s.replace(a, b))
    print("fixed", p)

fix("python/tools/notebook_edit_tool/notebook_edit_tool.py",
    "\t\t\t\tlogging.getLogger(__name__).debug(\r\n\t\t\t\t\"rewind file mutation note failed\", exc_info=True\r\n\t\t\t)",
    "\t\t\t\tlogging.getLogger(__name__).debug(\r\n\t\t\t\t\t\"rewind file mutation note failed\", exc_info=True\r\n\t\t\t\t)")
fix("python/tools/todo_write_tool/todo_write_tool.py",
    "\t\t\tlogging.getLogger(__name__).debug(\r\n\t\t\t\"session presence note_todos failed\", exc_info=True\r\n\t\t)",
    "\t\t\tlogging.getLogger(__name__).debug(\r\n\t\t\t\t\"session presence note_todos failed\", exc_info=True\r\n\t\t\t)")
