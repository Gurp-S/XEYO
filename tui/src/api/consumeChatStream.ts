import type {SseHandlers} from './sse.js';

/** 服务端完成标记与传输 EOF 分开判定；只消费现有单行 data 契约。 */
export async function consumeChatStream(
  body: ReadableStream<Uint8Array>, handlers: SseHandlers,
  onFrame: (line: string) => void, signal?: AbortSignal,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let carry = '';
  function consume(line: string): boolean {
    if (/^data:\s*\[DONE\]\s*$/.test(line.trim().replace(/^\uFEFF/, ''))) return true;
    onFrame(line);
    return false;
  }
  try {
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      carry += decoder.decode(value, {stream: true});
      const parts = carry.split('\n');
      carry = parts.pop() ?? '';
      for (const line of parts) {
        if (consume(line)) {handlers.onDone(); return;}
      }
    }
    carry += decoder.decode();
    if (consume(carry)) {handlers.onDone(); return;}
    if (signal?.aborted) {handlers.onDone(); return;}
    throw new Error('incomplete_stream: EOF before [DONE]');
  } catch (error) {
    if (signal?.aborted) {handlers.onDone(); return;}
    handlers.onError(error as Error);
  } finally {
    // 完成标记后无需等待服务端关闭连接；兼容轻量测试 reader。
    void reader.cancel?.().catch(() => {});
    reader.releaseLock?.();
  }
}
