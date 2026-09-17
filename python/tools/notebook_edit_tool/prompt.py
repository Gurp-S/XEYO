NOTEBOOK_EDIT_TOOL_NAME = "NotebookEdit"

DESCRIPTION = (
	"Edit a Jupyter notebook by cell (replace/insert/delete). Read input for .ipynb "
	"contains a structured cell index. Edit and Write do not handle .ipynb. "
	"insert without cell_idx appends; cell_type defaults to code. "
	"Each write may need user confirmation (permission ASK)."
)

IPYNB_REJECT = (
	"Jupyter Notebook (.ipynb) editing is cell-level through NotebookEdit; "
	"Edit and Write do not handle .ipynb."
)
