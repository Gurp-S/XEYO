import {computed} from '@preact/signals-react';
import {streamingTextSignal} from './streamSignal';
import {workflowDisplayText} from './workflowDisplayText';

/** 仅在可读文本开始出现或消失时通知导航组件，
 * 避免每个 token 都触发通知。 */
export const workflowStreamVisible = computed(() => Boolean(workflowDisplayText(streamingTextSignal.value)));
