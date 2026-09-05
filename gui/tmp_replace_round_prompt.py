from pathlib import Path
import re

path = Path(r"D:\lea\XenYon code\gui\src\components\MessageList.tsx")
text = path.read_text(encoding="utf-8")
pattern = re.compile(
    r"\n\s*\{round\.user \? \(.*?\n\s*\) : null\}\n\s*<div\n\s*ref=\{node => registerTranscriptLayer",
    re.S,
)
replacement = r'''
				{round.user ? (
					<div
						ref={node =>
							registerSticky(
								round.user!.id,
								node,
								round.user!.source !== 'remote',
							)
						}
						className={cn(
							'xy-prompt-sticky mt-2.5',
							PROMPT_X,
							editingMessageId === round.user.id && 'xy-prompt-sticky-editing',
						)}
						style={{
							zIndex: 40 + roundIndex,
							top: STICKY_TOP_PX,
						}}
					>
						<PromptBubble
							text={round.user.text}
							editable={round.user.source !== 'remote'}
							isEditing={editingMessageId === round.user.id}
							onEdit={event => beginEdit(round.user!, event)}
							rise={
								smoothness &&
								roundIndex === roundsLength - 1 &&
								Date.now() - round.user.createdAt < 900
							}
							editingText={editingText}
							onEditTextChange={onEditTextChange}
							editingSubmitting={editingSubmitting}
							cancelEdit={cancelEdit}
							submitEdit={submitEdit}
							model={model}
							modelOpen={modelOpen}
							modelMenuId={modelMenuId}
							toggleModel={toggleModel}
							closeModel={closeModel}
							editingTextareaRef={editingTextareaRef}
							promptEditRef={promptEditRef}
							editModelMenuRef={editModelMenuRef}
							anyStreaming={anyStreaming}
							stopGeneration={stopGeneration}
							resizeEditingTextarea={resizeEditingTextarea}
						/>
					</div>
				) : null}
				<div
					ref={node => registerTranscriptLayer'''

updated, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise SystemExit(f"expected one RoundHost prompt branch, found {count}")
path.write_text(updated, encoding="utf-8", newline="\n")
print("replaced one RoundHost prompt branch")
