"""ask_user_question_tool 描述文本。"""

DESCRIPTION = (
	"Ask the user a clarifying question and wait. "
	"Use when you must confirm a requirement, path, option, or preference. "
	"Provide question (+ optional options/default), or questions[] for multiple "
	"(numbered into one pause). "
	"The turn pauses until they answer (next turn gets the tool result)."
)
