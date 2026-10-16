import {useEffect, useRef} from 'react';
import {isImeComposing} from '@/lib/ime';
import {popEscLayer, pushEscLayer} from '@/lib/escStack';

type Props = {label: string; value: string; pending: boolean; error?: string | null; maxLength?: number;
	onChange: (text: string) => void; onSave: () => void; onCancel: () => void; saveLabel?: string};

/** Shared multiline editing contract: Enter inserts a line, modifier+Enter saves. */
export function DockTextEditor({label,value,pending,error,maxLength,onChange,onSave,onCancel,saveLabel='保存'}: Props) {
	const callbacks = useRef({pending,onCancel});callbacks.current={pending,onCancel};
	useEffect(()=>{
		const key=`dock-edit:${label}`;
		pushEscLayer(key,()=>{if(!callbacks.current.pending)callbacks.current.onCancel();});
		return ()=>popEscLayer(key);
	},[label]);
	return <div className="xy-dock-editor" aria-busy={pending}>
		<label>{label}<textarea aria-label={label} placeholder={label} value={value} autoFocus rows={3} maxLength={maxLength} disabled={pending}
			onChange={e=>onChange(e.target.value)} onKeyDown={e=>{
				if(isImeComposing(e.nativeEvent))return;
				if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();if(!pending&&value.trim())onSave();}
				if(e.key==='Escape'){e.preventDefault();e.stopPropagation();if(!pending)onCancel();}
			}} /></label>
		{error && <p className="xy-dock-error" role="alert">{error}</p>}
		<footer><span>Enter 换行 · Ctrl/⌘ Enter 保存</span><button type="button" onClick={onCancel} disabled={pending}>取消</button><button type="button" className="is-primary" onClick={onSave} disabled={pending||!value.trim()}>{pending?'保存中…':saveLabel}</button></footer>
	</div>;
}
