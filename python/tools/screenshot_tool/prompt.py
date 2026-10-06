"""screenshot_tool 描述文本。"""

DESCRIPTION = (
	"Capture the primary monitor; returns the saved path. "
	"The capture covers the primary monitor and can contain screen/UI content. "
	"If WeChat is logged in, a copy is sent to the phone in the background — "
	"the send is asynchronous. view=true returns an image for inspection. "
	"Availability follows the local desktop: it needs a display, and that fact is "
	"reported by the engine as env_facts desktop (absent/true = desktop present)."
)
