import {cn} from '@/lib/utils';

type SwitchProps = {
	checked: boolean;
	disabled?: boolean;
	onChange: () => void;
	label: string;
};

/**
 * 开关（role=switch）。视觉对应 extensions.css 的 .ext-toggle 轨道/旋钮：
 * on = accent 轨道，off = paper-deep + 细 ring；disabled 半透明。
 * 由 PluginsPanel 内部 Toggle 提升而来，行为逐字等价。
 */
export function Switch({checked, disabled = false, onChange, label}: SwitchProps) {
	return (
		<button
			type="button"
			role="switch"
			aria-checked={checked}
			aria-label={label}
			disabled={disabled}
			data-checked={checked}
			onClick={onChange}
			className={cn(
				'ext-toggle xy-press relative h-5 w-9 shrink-0 rounded-full',
				checked ? 'bg-accent' : 'bg-paper-deep ring-1 ring-line',
				disabled && 'opacity-40',
			)}
		>
			<span
				aria-hidden="true"
				className={cn(
					'ext-toggle-knob absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-paper',
					'shadow-sm',
					checked ? 'translate-x-4' : 'translate-x-0',
				)}
			/>
		</button>
	);
}
