XEYO_UI_TOOL_NAME = "XeyoUI"

# Keep DESCRIPTION short: it is sent every turn in the tool schema.
DESCRIPTION = (
	"XEYO desktop UI (GUI only). "
	"list_sessions; "
	"open_preview path=…; "
	"open_panel panel=git|terminal|history|map|commits|browser; "
	"browser url=…|op=reload|back|fwd|ext|close; "
	"show_tool_flow show=bool; "
	"send_to_session session_id=… text=…. "
	"list_sessions before send_to_session; never current/side id. "
	"UI-only — not Read/Git/Bash/WebFetch."
)
