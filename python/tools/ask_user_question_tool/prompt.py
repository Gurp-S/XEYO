"""ask_user_question_tool 描述文本。"""

DESCRIPTION = (
	"Pauses the turn while asking the user one or more questions. "
	"Pass questions[] (each: id, question, optional header/detail/options/"
	"multiSelect/default) for multiple questions; the answer returns as JSON "
	'{\"answers\":[{\"id\",\"selected\":[labels],\"custom\"?}]} — skipped '
	"questions carry an empty selected[]. "
	"Legacy single form (question + options/default) returns the raw answer "
	"text. The turn pauses until they answer."
)
