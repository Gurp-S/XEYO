import {computed} from '@preact/signals-react';
import {streamingTextSignal} from './streamSignal';
import {workflowDisplayText} from './workflowDisplayText';

/** Only notify the navigator when readable prose starts or disappears,
 * rather than on every token. */
export const workflowStreamVisible = computed(() => Boolean(workflowDisplayText(streamingTextSignal.value)));
