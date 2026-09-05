NOTEBOOK_EDIT_TOOL_NAME = "NotebookEdit"

DESCRIPTION = (
	"Edit a Jupyter notebook by cell (replace/insert/delete). Read the .ipynb "
	"first (structured cell index). Do not use Edit or Write on .ipynb. "
	"insert without cell_idx appends; cell_type defaults to code. "
	"Each write may need user confirmation (permission ASK)."
)

IPYNB_REJECT = (
	"Jupyter Notebook (.ipynb) must be edited with the NotebookEdit tool "
	"(cell-level). Do not use Edit/Write on .ipynb."
)
