/**
 * 过程旁白：「让我看看…」「我来帮你找到…」等工具前口头禅。
 * 进行中可展示；工具收束 / done 后不展示。
 */

const NARRATION_LINE =
	/^\s*(?:(?:好的|嗯|哦|行|可以|OK|Alright)[，,。!\s]*)?(?:让我(?:来|先|再|重新)?(?:仔细)?(?:看(?:看|一下|下)?|查看|检查|搜索|搜一下|找(?:一下)?|读(?:取|一下)?|打开|确认|分析|试试|试着|处理|改(?:一下)?|写|运行|执行|浏览|翻看|排查|定位|理解|梳理|总结|调研)|我(?:来|先|再)(?:帮你|仔细)?(?:找(?:到|一下)?|看(?:看|一下|下)?|查看|检查|搜索|搜一下|读(?:取|一下)?|打开|确认|分析|试试|处理|排查|定位)|(?:接下来|现在)(?:我)?(?:来|先)?(?:看|查|搜|读|打开|检查|分析|处理|找)|(?:Let\s+me|I(?:'ll| will)|I(?:'m| am)\s+going\s+to)\s+(?:just\s+)?(?:look|check|search|read|open|try|run|examine|inspect|find|see|review|verify|dig|explore|scan|investigate)\b).{0,200}?[。．.！!？?\s…:：]*$/i;

const NARRATION_OPENER =
	/^\s*(?:(?:好的|嗯|哦|行|可以)[，,。!\s]*)?(?:我来帮你|让我|我先|现在让我|接下来我?来?|Let\s+me\b|I(?:'ll| will)\b)/i;

/** 整段是否只是过程旁白（与后端 process_narration 对齐，并覆盖「我来帮你…让我先…」）。 */
export function isProcessNarration(text: string): boolean {
	const raw = (text || '').trim();
	if (!raw) {
		return false;
	}
	// 明显是结论正文
	if (
		/^#{1,3}\s/m.test(raw) ||
		/文件位置\s*[:：]|代码行数\s*[:：]|根据.{0,24}分析/.test(raw) ||
		raw.length > 280
	) {
		return false;
	}
	if (NARRATION_OPENER.test(raw)) {
		return true;
	}
	const parts = raw.split(/\n+/);
	let saw = false;
	for (const part of parts) {
		const line = part.trim();
		if (!line) {
			continue;
		}
		if (!NARRATION_LINE.test(line)) {
			return false;
		}
		saw = true;
	}
	return saw;
}
