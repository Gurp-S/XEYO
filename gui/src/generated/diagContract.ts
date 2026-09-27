/**
 * 由 `py -3.11 -m diagnostics.export_contract` 生成 —— 不要手改。
 *
 * 内容是诊断层生产者**实际会发出**的枚举值（扫描 add_gap 调用、BOUNDARIES、
 * RULES、_SHOWN_TEXT、loss_chain 的状态常量与 verdict 字面量得到）。界面的 ratchet
 * 测试用它保证：新增枚举值而没有中文说法时，构建期就红，而不是等用户看到
 * `recovered_outside_window`。
 */

export type DiagContractGapReason = {boundary: string; reason: string};

export const DIAG_BOUNDARIES: ReadonlyArray<{name: string; label: string}> = [
	{name: 'user_request', label: '用户请求 / 接收'},
	{name: 'resume_schedule', label: '会话恢复与调度'},
	{name: 'instruction_context', label: '指令与上下文'},
	{name: 'wsc_fold', label: 'WSC 折叠'},
	{name: 'adapter', label: '适配器最终请求'},
	{name: 'model_request', label: '模型请求与响应'},
	{name: 'tool_permission', label: '工具与权限'},
	{name: 'background_job', label: '后台任务'},
	{name: 'file_verifier', label: '文件与验收'},
	{name: 'sse_gui', label: 'SSE / 界面'},
];

export const DIAG_RULE_IDS: readonly string[] = [
	'tool_pair_integrity',
	'instruction_drift',
	'cold_reference',
	'frozen_head',
	'provider_stream_failure',
	'permission_block',
	'tool_failure',
	'tool_routing',
	'wire_gap',
	'incomplete_run',
	'repeated_failure',
	'usage_accounting',
	'verifier',
];

export const DIAG_GAP_REASONS: ReadonlyArray<DiagContractGapReason> = [
	{boundary: 'adapter', reason: 'not_captured'},
	{boundary: 'adapter', reason: 'out_of_window'},
	{boundary: 'adapter', reason: 'source_absent'},
	{boundary: 'file_verifier', reason: 'field_missing'},
	{boundary: 'file_verifier', reason: 'not_recorded'},
	{boundary: 'file_verifier', reason: 'out_of_window'},
	{boundary: 'file_verifier', reason: 'source_absent'},
	{boundary: 'instruction_context', reason: 'no_records'},
	{boundary: 'instruction_context', reason: 'not_comparable'},
	{boundary: 'instruction_context', reason: 'not_found_in_full_file'},
	{boundary: 'instruction_context', reason: 'out_of_window'},
	{boundary: 'instruction_context', reason: 'read_failed'},
	{boundary: 'instruction_context', reason: 'recovered_outside_window'},
	{boundary: 'instruction_context', reason: 'source_absent'},
	{boundary: 'model_request', reason: 'out_of_window'},
	{boundary: 'model_request', reason: 'recovered_outside_window'},
	{boundary: 'model_request', reason: 'source_absent'},
	{boundary: 'model_request', reason: 'unattributed_rows'},
	{boundary: 'wsc_fold', reason: 'no_records'},
	{boundary: 'wsc_fold', reason: 'out_of_window'},
	{boundary: 'wsc_fold', reason: 'source_absent'},
	{boundary: 'wsc_fold', reason: 'unattributed_rows'},
];

export const DIAG_SESSION_CONSTANT_GAPS: ReadonlyArray<DiagContractGapReason> = [
	{boundary: 'adapter', reason: 'not_captured'},
	{boundary: 'adapter', reason: 'source_absent'},
	{boundary: 'file_verifier', reason: 'not_recorded'},
	{boundary: 'file_verifier', reason: 'out_of_window'},
	{boundary: 'file_verifier', reason: 'source_absent'},
	{boundary: 'instruction_context', reason: 'no_records'},
	{boundary: 'instruction_context', reason: 'out_of_window'},
	{boundary: 'instruction_context', reason: 'recovered_outside_window'},
	{boundary: 'model_request', reason: 'out_of_window'},
	{boundary: 'model_request', reason: 'recovered_outside_window'},
	{boundary: 'model_request', reason: 'unattributed_rows'},
	{boundary: 'wsc_fold', reason: 'no_records'},
	{boundary: 'wsc_fold', reason: 'unattributed_rows'},
];

export const DIAG_SHOWN_STATES: readonly string[] = [
	'folded_out',
	'no_obligation',
	'not_shown',
	'shown',
	'unprovable',
];

export const DIAG_SHOWN_TEXTS: Readonly<Record<string, string>> = {
	'folded_out': '被折叠移出投影（未送达）',
	'no_obligation': '没有可比对的约束文本',
	'not_shown': '不在留存的那一份发射投影里',
	'shown': '已进入模型实际收到的内容',
	'unprovable': '无法证明是否送达',
};

export const DIAG_COVERAGE_SOURCES: readonly string[] = [
	'audit',
	'captures',
	'fold_events',
	'jobs',
	'transcript',
	'usage',
	'wire_drops',
	'working',
];

export const DIAG_FACT_STATES: readonly string[] = [
	'absent',
	'folded_out',
	'found',
	'not_captured',
	'not_recorded',
	'unreadable',
];

export const DIAG_FACT_VERDICTS: readonly string[] = [
	'folded_out_of_projection',
	'kept_through',
	'lost_before:emitted',
	'not_in_source_history',
	'unknown',
];

export const DIAG_PARTIES: readonly string[] = [
	'engine',
	'environment',
	'mixed',
	'model',
	'undetermined',
];

export const DIAG_PAYLOAD_KEYS: Readonly<Record<string, readonly string[]>> = {
	attribution: ['attributed', 'confirmed_count', 'first_anomaly_boundary', 'first_anomaly_label', 'last_evidenced_boundary', 'last_evidenced_label', 'statement', 'suspected_count', 'unknown_count'],
	cause: ['code', 'does_not_prove', 'evidence', 'evidence_total', 'label', 'party', 'proves'],
	evidence: ['detail', 'locator', 'ref_id', 'source'],
	fault: ['cause_statement', 'causes', 'chain', 'engine_confirmed', 'environment_confirmed', 'missing_evidence', 'no_turn_records', 'not_claimed', 'obligation', 'primary_cause', 'primary_cause_label', 'responsibility', 'responsibility_label', 'shown_to_model', 'shown_to_model_note', 'task_outcome', 'task_outcome_label', 'transport_gap', 'why'],
	finding: ['allowed_conclusion', 'boundary', 'component', 'coverage_gap', 'evidence', 'impact', 'phenomenon', 'rule_id', 'rule_version', 'status'],
	gap: ['boundary', 'detail', 'reason', 'scope'],
	model_request: ['attempt_keys', 'attempts', 'capture', 'evidence', 'model', 'model_request_id', 'projection_id', 'provider', 'tool_use_ids', 'turn_id', 'usage_by_attempt'],
	report: ['attribution', 'boundaries', 'captures', 'coverage', 'evidence_rows', 'fault', 'findings', 'folds', 'gaps', 'generated_at', 'identity', 'jobs', 'model_requests', 'notes', 'permissions', 'pin_count', 'pins', 'projections', 'schema_version', 'session_id', 'tool_calls', 'turn_id', 'usage', 'usage_summary', 'versions', 'windows', 'wire_drops', 'working'],
	tool_call: ['action_id', 'approval_ids', 'error_kind', 'evidence', 'finished', 'is_error', 'model_request_id', 'paired', 'projection_id', 'result_message_id', 'started', 'tool_name', 'tool_use_id', 'turn_id'],
	usage_summary: ['cost_basis', 'cost_sources', 'estimated_total_cny', 'finished_attempts', 'priced_attempts', 'statement', 'total_is_partial', 'unknown_cost_attempts', 'unknown_cost_keys', 'unlinked_usage_rows', 'unpriced_attempts', 'unpriced_keys', 'usage_window_complete', 'usage_window_present'],
	window: ['bytes_read', 'complete', 'locator', 'note', 'present', 'rows_capped', 'rows_matched', 'rows_other_session', 'rows_other_turn', 'rows_outside_window', 'rows_scanned', 'rows_unattributed', 'rows_unparsable', 'source', 'truncated'],
};
