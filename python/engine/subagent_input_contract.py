"""Delegated tasks belong to user input; environment observations are separate."""
from msgtypes.message import notice_note, user_message


def initial_messages(prior, task: str, recent_changes: str):
    messages = list(prior)
    if recent_changes.strip():
        from prompt.notice_channel import wrap_notice
        messages.append(notice_note(wrap_notice(recent_changes, "recent_changes"),
                                    key="recent_changes", fp="", kind="event"))
    # Every invocation, including a resumed sidechain, carries its actual task.
    messages.append(user_message(task))
    return messages
