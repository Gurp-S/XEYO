import {ArrowUp, ChevronDown, Paperclip, Plus, Square, X} from 'lucide-react';
import {
	useEffect,
	useId,
	useRef,
	useState,
	type ClipboardEvent,
	type KeyboardEvent,
} from 'react';
import {uploadFile} from '@/lib/api';
import {
	clearComposerDraft,
	dropComposerDraft,
	getComposerDraft,
	setComposerDraft,
	type DraftAttachment,
	type DraftFileAttachment,
	type DraftImageAttachment,
} from '@/lib/composerDrafts';
import {cn, uid} from '@/lib/utils';
import {isSmoothnessOn, useSettingsStore} from '@/stores/settingsStore';
import {useChatUiStore, useChatUiStoreApi} from '@/stores/chatUiStore';
import {useRemoteStore} from '@/stores/remoteStore';
import {ModelPicker} from '@/components/ModelPicker';

type FileAttachment = DraftFileAttachment;
type ImageAttachment = DraftImageAttachment;
type Attachment = DraftAttachment;

const MAX_IMAGES = 8;
const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
/** 与左右 32px 按钮同高，保证空态垂直居中；封顶后内部滚动 */
const TA_MIN_PX = 32;
const TA_MAX_PX = 120;

function SendStopButton({
	streaming,
	canSend,
	smoothness,
	onSend,
	onStop,
}: {
	streaming: boolean;
	canSend: boolean;
	smoothness: boolean;
	onSend: () => void;
	onStop: () => void;
}) {
	if (!smoothness) {
		if (streaming) {
			return (
				<button
					type="button"
											onClick={onStop}
						aria-label="停止生成"
						title="停止生成"
						className="xy-press flex h-8 w-8 items-center justify-center rounded-full bg-ink text-paper hover:bg-ink-soft"
						
				>
					<Square className="h-3 w-3 fill-current" />
				</button>
			);
		}
		return (
			<button
				type="button"
					onClick={onSend}
aria-label="发送"
									title="发送"
									disabled={!canSend}
				className={cn(
					'flex h-8 w-8 items-center justify-center rounded-full transition-colors',
					canSend
						? 'bg-accent text-on-accent hover:bg-accent-hover'
						: 'cursor-not-allowed bg-paper-deep text-mute',
				)}
				
			>
				<ArrowUp className="h-4 w-4" strokeWidth={2.25} />
			</button>
		);
	}
	return (
		<button
			type="button"
			onClick={streaming ? onStop : onSend}
			disabled={!streaming && !canSend}
			className={cn(
				'xy-press relative flex h-8 w-8 items-center justify-center rounded-full',
				streaming
					? 'bg-ink text-paper hover:bg-ink-soft'
					: canSend
						? 'bg-accent text-on-accent hover:bg-accent-hover'
						: 'cursor-not-allowed bg-paper-deep text-mute',
			)}
			
			aria-label={streaming ? '停止生成' : '发送'}
				title={streaming ? '停止生成' : '发送'}
		>
			<ArrowUp
				className={cn(
					'xy-send-stop-icon absolute h-4 w-4',
					streaming ? 'scale-90 opacity-0' : 'scale-100 opacity-100',
				)}
				strokeWidth={2.25}
				aria-hidden
			/>
			<Square
				className={cn(
					'xy-send-stop-icon absolute h-3 w-3 fill-current',
					streaming ? 'scale-100 opacity-100' : 'scale-90 opacity-0',
				)}
				aria-hidden
			/>
		</button>
	);
}

export function Composer() {
	const [value, setValue] = useState('');
	const [attachments, setAttachments] = useState<Attachment[]>([]);
	const [uploading, setUploading] = useState(false);
	const [dragOver, setDragOver] = useState(false);
	const fileRef = useRef<HTMLInputElement>(null);
	const taRef = useRef<HTMLTextAreaElement>(null);
	const attachmentsRef = useRef(attachments);
	attachmentsRef.current = attachments;
	const activeId = useChatUiStore(s => s.activeId);
	const streamingSessionId = useChatUiStore(s => s.streamingSessionId);
	const isLoading = useChatUiStore(s => s.isLoading);
	const statusText = useChatUiStore(s => s.statusText);
	const sendMessage = useChatUiStore(s => s.sendMessage);
		const chatUiStoreApi = useChatUiStoreApi();
	const stopGeneration = useChatUiStore(s => s.stopGeneration);
	const composerInsertSeq = useChatUiStore(s => s.composerInsertSeq);
	const composerFocusSeq = useChatUiStore(s => s.composerFocusSeq);
	const model = useSettingsStore(s => s.model);
	const apiKey = useSettingsStore(s => s.apiKey);
	const openSettings = useSettingsStore(s => s.openSettings);
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));
	const remoteLoggedIn = useRemoteStore(s => s.loggedIn);
	const [modelOpen, setModelOpen] = useState(false);
	const modelMenuRef = useRef<HTMLDivElement>(null);
	const modelMenuId = useId();
	const activeIdRef = useRef(activeId);
	const valueRef = useRef(value);
	valueRef.current = value;
	const activeStreaming =
		isLoading && Boolean(activeId) && activeId === streamingSessionId;
	const anyStreaming = isLoading && Boolean(streamingSessionId);

	const images = attachments.filter(
		(a): a is ImageAttachment => a.kind === 'image',
	);
	const files = attachments.filter(
		(a): a is FileAttachment => a.kind === 'file',
	);

	/** 按 session 草稿：保存离开的 session，恢复进入的 session（仅内存）。 */
	useEffect(() => {
		const prevId = activeIdRef.current;
		if (prevId && prevId !== activeId) {
			setComposerDraft(prevId, {
				text: valueRef.current,
				attachments: attachmentsRef.current,
			});
		}
		const loaded = activeId ? getComposerDraft(activeId) : undefined;
		setValue(loaded?.text ?? '');
		setAttachments(loaded ? loaded.attachments.slice() : []);
		activeIdRef.current = activeId;
	}, [activeId]);

	useEffect(() => {
		if (composerInsertSeq === 0) {
			return;
		}
		const snip = useChatUiStoreApi().getState().lastComposerInsert;
		if (!snip) {
			return;
		}
		setAttachments(prev => {
			if (
				prev.some(
					a =>
						a.kind === 'file' &&
						a.name === snip.name &&
						a.text === snip.text,
				)
			) {
				return prev;
			}
			return [
				...prev,
				{
					kind: 'file',
					id: uid('snip'),
					name: snip.name,
					text: snip.text,
				},
			];
		});
	}, [composerInsertSeq]);

	useEffect(() => {
		if (composerFocusSeq === 0) {
			return;
		}
		taRef.current?.focus();
	}, [composerFocusSeq]);

	useEffect(() => {
		const onKey = (e: globalThis.KeyboardEvent) => {
			if (e.key !== 'Escape') {
				return;
			}
			const st = useChatUiStoreApi().getState?.();
			if (st?.isLoading && st.streamingSessionId) {
				e.preventDefault();
				void stopGeneration();
			}
		};
		window.addEventListener('keydown', onKey);
		return () => window.removeEventListener('keydown', onKey);
	}, [stopGeneration]);

	useEffect(() => {
		if (!modelOpen) {
			return;
		}
		const onDoc = (e: MouseEvent) => {
			if (!modelMenuRef.current?.contains(e.target as Node)) {
				setModelOpen(false);
			}
		};
		const onKey = (e: globalThis.KeyboardEvent) => {
			if (e.key === 'Escape') {
				setModelOpen(false);
			}
		};
		document.addEventListener('mousedown', onDoc);
		document.addEventListener('keydown', onKey);
		return () => {
			document.removeEventListener('mousedown', onDoc);
			document.removeEventListener('keydown', onKey);
		};
	}, [modelOpen]);

	useEffect(() => {
		if (!remoteLoggedIn) {
			return;
		}
		setAttachments(prev => {
			const next = [];
			for (const a of prev) {
				if (a.kind === 'image') {
					URL.revokeObjectURL(a.previewUrl);
					continue;
				}
				next.push(a);
			}
			return next;
		});
	}, [remoteLoggedIn]);

	useEffect(() => {
		return () => {
			for (const a of attachmentsRef.current) {
				if (a.kind === 'image') {
					URL.revokeObjectURL(a.previewUrl);
				}
			}
		};
	}, []);

	const resizeTa = () => {
		const el = taRef.current;
		if (!el) {
			return;
		}
		el.style.height = 'auto';
		const measured = el.scrollHeight;
		const next = Math.min(TA_MAX_PX, Math.max(TA_MIN_PX, measured));
		el.style.height = `${next}px`;
		el.style.overflowY = measured > TA_MAX_PX ? 'auto' : 'hidden';
	};

	useEffect(() => {
		resizeTa();
	}, [value]);

	const removeAttachment = (id: string) => {
		setAttachments(prev => {
			const target = prev.find(a => a.id === id);
			if (target?.kind === 'image') {
				URL.revokeObjectURL(target.previewUrl);
			}
			return prev.filter(a => a.id !== id);
		});
	};

	const clearAttachments = () => {
		setAttachments(prev => {
			for (const a of prev) {
				if (a.kind === 'image') {
					URL.revokeObjectURL(a.previewUrl);
				}
			}
			return [];
		});
	};

	const addImages = (list: File[]) => {
		const next: ImageAttachment[] = [];
		for (const file of list) {
			if (!file.type.startsWith('image/')) {
				continue;
			}
			if (file.size > MAX_IMAGE_BYTES) {
				alert(`图片 ${file.name} 超过 8MB`);
				continue;
			}
			next.push({
				kind: 'image',
				id: uid('img'),
				name: file.name || 'paste.png',
				previewUrl: URL.createObjectURL(file),
				mime: file.type || 'image/png',
				bytes: file.size,
			});
		}
		if (next.length === 0) {
			return;
		}
		setAttachments(prev => {
			const room = MAX_IMAGES - prev.filter(a => a.kind === 'image').length;
			if (room <= 0) {
				for (const n of next) {
					URL.revokeObjectURL(n.previewUrl);
				}
				alert(`最多添加 ${MAX_IMAGES} 张图片`);
				return prev;
			}
			const take = next.slice(0, room);
			for (const n of next.slice(room)) {
				URL.revokeObjectURL(n.previewUrl);
			}
			return [...prev, ...take];
		});
	};

	const onPickFiles = async (fileList: FileList | File[] | null) => {
		if (!fileList) {
			return;
		}
		const arr = Array.from(fileList);
		const imgs = arr.filter(f => f.type.startsWith('image/'));
		const others = arr.filter(f => !f.type.startsWith('image/'));
		if (imgs.length && !remoteLoggedIn) {
			addImages(imgs);
		}
		for (const file of others) {
			setUploading(true);
			try {
				const res = await uploadFile(file);
				setAttachments(prev => [
					...prev,
					{
						kind: 'file',
						id: uid('file'),
						name: res.filename || file.name,
						text: res.text,
					},
				]);
			} catch (err) {
				alert(err instanceof Error ? err.message : String(err));
			} finally {
				setUploading(false);
			}
		}
		if (fileRef.current) {
			fileRef.current.value = '';
		}
	};

	const onPaste = (e: ClipboardEvent<HTMLTextAreaElement>) => {
		const items = e.clipboardData?.items;
		if (!items) {
			return;
		}
		const imageFiles: File[] = [];
		for (const item of items) {
			if (item.kind === 'file' && item.type.startsWith('image/')) {
				const f = item.getAsFile();
				if (f) {
					imageFiles.push(f);
				}
			}
		}
		if (imageFiles.length === 0 || remoteLoggedIn) {
			return;
		}
		e.preventDefault();
		addImages(imageFiles);
	};

	const buildPayload = () => {
		const parts = [value.trim()];
		for (const a of files) {
			parts.push(`\n\n[附件: ${a.name}]\n\`\`\`\n${a.text}\n\`\`\`\n`);
		}
		if (images.length > 0) {
			// 占位符，待 vision/upload API 接入
			const names = images.map(i => i.name).join(', ');
			parts.push(
				`\n\n[图片 ×${images.length}: ${names}]\n（图片已附加在本地，后端联调后发送）`,
			);
		}
		return parts.join('').trim();
	};

	const canSend =
		!remoteLoggedIn && (Boolean(value.trim()) || attachments.length > 0);

	const onSend = () => {
		const text = buildPayload();
		// 单路在途流；任意 session 生成中则阻止发送。
		if (remoteLoggedIn || !text || anyStreaming) {
			return;
		}
		const sessionId = activeId;
		const draftText = value;
		const draftAttachments = attachments;
		// 仅在 store 接受消息后清除（乐观 UI 已落地）。
		void (async () => {
			const started = await sendMessage(text);
			const stillHere =
				sessionId != null &&
				chatUiStoreApi.getState().activeId === sessionId;
			if (!started) {
				if (sessionId) {
					setComposerDraft(sessionId, {
						text: draftText,
						attachments: draftAttachments,
					});
				}
				if (stillHere) {
					setValue(draftText);
					setAttachments(draftAttachments);
				}
				const st = chatUiStoreApi.getState();
				if (st.isLoading && st.streamingSessionId) {
					window.alert('当前有生成进行中，请先停止或稍候再试');
				}
				return;
			}
			// 发送会关闭此 session 的草稿（仅内存）。
			if (sessionId) {
				if (stillHere) {
					dropComposerDraft(sessionId);
					setValue('');
					clearAttachments();
				} else {
					clearComposerDraft(sessionId);
				}
			} else if (stillHere) {
				setValue('');
				clearAttachments();
			}
			if (stillHere) {
				requestAnimationFrame(() => {
					if (taRef.current) {
						taRef.current.style.height = `${TA_MIN_PX}px`;
						taRef.current.style.overflowY = 'hidden';
						taRef.current.focus();
					}
				});
			}
		})();
	};

	const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			onSend();
		}
	};

	return (
		<div className="shrink-0 px-3 pb-2.5 pt-1.5 sm:px-5 sm:pb-4">
			<div className="mx-auto w-full max-w-3xl">
				{remoteLoggedIn ? null : !apiKey.trim() && !anyStreaming ? (
					<p className="mb-1.5 px-1 font-sans text-[11px] text-mute">
						尚未配置 API Key。
						<button
							type="button"
							className="ml-1 text-accent underline-offset-2 hover:underline"
							onClick={() => openSettings()}
						>
							打开设置
						</button>
					</p>
				) : null}
				{anyStreaming && (
					<p className="anim-fade mb-1.5 px-1 font-mono text-[11px] text-mute">
						<span className="xy-thinking">
							{activeStreaming
								? statusText || 'thinking…'
								: '另一会话生成中…'}
						</span>
						<span className="mx-2 text-line">·</span>
						Esc 中断
					</p>
				)}

				<div
					onDragEnter={e => {
						if (remoteLoggedIn) {
							return;
						}
						e.preventDefault();
						setDragOver(true);
					}}
					onDragOver={e => {
						if (remoteLoggedIn) {
							return;
						}
						e.preventDefault();
						setDragOver(true);
					}}
					onDragLeave={e => {
						e.preventDefault();
						if (e.currentTarget.contains(e.relatedTarget as Node)) {
							return;
						}
						setDragOver(false);
					}}
					onDrop={e => {
						e.preventDefault();
						setDragOver(false);
						if (remoteLoggedIn) {
							return;
						}
						void onPickFiles(e.dataTransfer.files);
					}}
					className={cn(
						/* 与用户气泡相同的半透明填充/边框 */
						'xy-surface xy-user-bubble xy-composer-surface relative',
							'transition-[border-color,box-shadow,border-radius] duration-200',
						images.length || files.length ? 'rounded-2xl' : 'rounded-full',
							dragOver && '!border-accent ring-2 ring-accent/20',
					)}
				>
					{images.length > 0 && !remoteLoggedIn && (
						<div className="flex flex-wrap gap-2 border-b border-line/40 px-3 pt-2.5 pb-2">
							{images.map(img => (
								<div
									key={img.id}
									className="anim-pop group relative h-14 w-14 overflow-hidden rounded-xl border border-line/70 bg-paper-deep/60"
								>
									<img
										src={img.previewUrl}
										alt={img.name}
										className="h-full w-full object-cover"
										draggable={false}
									/>
									<button
										type="button"
										aria-label={`移除 ${img.name}`}
										onClick={() => removeAttachment(img.id)}
										className="xy-icon-btn absolute top-0.5 right-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-ink/75 text-paper opacity-90 hover:bg-ink"
									>
										<X className="h-3 w-3" />
									</button>
								</div>
							))}
						</div>
					)}

					{files.length > 0 && !remoteLoggedIn && (
						<div className="flex flex-wrap gap-1.5 border-b border-line/40 px-3 pt-2 pb-1.5">
							{files.map(a => (
								<span
									key={a.id}
									className="anim-pop inline-flex max-w-full items-center gap-1.5 rounded-lg border border-line bg-paper px-2 py-0.5 font-mono text-[11px] text-ink-soft"
								>
									<Paperclip className="h-3 w-3 shrink-0 text-accent" />
									<span className="truncate">{a.name}</span>
									<button
										type="button"
										onClick={() => removeAttachment(a.id)}
										className="xy-icon-btn shrink-0 text-mute hover:text-danger"
									>
										<X className="h-3 w-3" />
									</button>
								</span>
							))}
						</div>
					)}

					{/* + | 输入 | 模型 | 发送：同高 32px / leading-8，同一基线；多行时右侧贴底 */}
					<div className="flex items-end gap-2 px-2 py-[6px]">
						{remoteLoggedIn ? (
							<div
								className="flex min-h-8 w-full items-center justify-center px-3 font-sans text-[14px] leading-8 text-mute"
								aria-label="远程已连接"
							>
								远程已连接
							</div>
						) : (
							<>
						<input
							ref={fileRef}
							type="file"
							multiple
							accept="image/*,*/*"
							className="hidden"
							onChange={e => void onPickFiles(e.target.files)}
						/>
						<button
							type="button"
							disabled={uploading || anyStreaming}
							onClick={() => fileRef.current?.click()}
							className="xy-icon-btn flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-mute hover:bg-paper-deep hover:text-ink disabled:opacity-40"
							
						>
							<Plus className="h-4 w-4" strokeWidth={2} />
						</button>

						<textarea
							ref={taRef}
							value={value}
							onChange={e => setValue(e.target.value)}
							onKeyDown={onKeyDown}
							onPaste={onPaste}
							rows={1}
							placeholder="描述任务… Enter 发送"
								className="box-border min-h-8 max-h-[120px] w-full flex-1 resize-none bg-transparent py-1 font-sans text-[14px] leading-6 text-ink outline-none placeholder:text-mute/65"
						/>

						<div className="flex h-8 shrink-0 items-center gap-1">
							<div ref={modelMenuRef} className="relative hidden sm:block">
								<button
									type="button"
									aria-haspopup="listbox"
									aria-expanded={modelOpen}
									aria-controls={modelMenuId}
									disabled={anyStreaming}
									onClick={() => setModelOpen(v => !v)}
									className={cn(
										'inline-flex h-7 max-w-[9.5rem] items-center gap-1 rounded-full px-2 font-mono text-[11px] leading-none text-mute',
										'hover:bg-ink/[0.06] hover:text-ink disabled:opacity-40',
										modelOpen && 'bg-ink/[0.08] text-ink',
									)}
									
								>
									<span className="truncate">{model}</span>
									<ChevronDown
										className={cn(
											'h-3 w-3 shrink-0 opacity-50 transition-transform',
											modelOpen && 'rotate-180 opacity-70',
										)}
									/>
								</button>
								<ModelPicker
									open={modelOpen}
									menuId={modelMenuId}
									disabled={anyStreaming}
								/>
							</div>

							<SendStopButton
								streaming={anyStreaming}
								canSend={canSend}
								smoothness={smoothness}
								onSend={onSend}
								onStop={() => void stopGeneration()}
							/>
						</div>
							</>
						)}
					</div>

					{dragOver ? (
						<div className="pointer-events-none absolute inset-0 flex items-center justify-center rounded-[inherit] bg-accent/8 font-mono text-xs text-accent">
							松开以添加图片 / 文件
						</div>
					) : null}
				</div>
			</div>
		</div>
	);
}
