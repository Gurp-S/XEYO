/** A bounded-latency delta batch; callers flush at every stream boundary. */
export function createDeltaBuffer(
  emit: (id: string, text: string, previousId: string) => void,
  delay = 16,
) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let pending: {id: string; previousId: string; chunks: string[]} | undefined;
  const flush = () => {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
    const batch = pending;
    pending = undefined;
    if (batch) emit(batch.id, batch.chunks.join(''), batch.previousId);
  };
  return {
    flush,
    push(id: string, text: string, previousId: string) {
      if (pending && pending.id !== id) flush();
      if (!pending) pending = {id, previousId, chunks: []};
      pending.chunks.push(text);
      if (timer === undefined) timer = setTimeout(flush, delay);
    },
  };
}
