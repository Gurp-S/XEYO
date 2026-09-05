import type {ContextSnapshot} from '@/pasture/context/ContextStage';
import type {CharacterLocation} from '@/pasture/core/ContextIslandState';

export type PetContextPayload = {
  sessionId: string | null;
  snapshot: Partial<ContextSnapshot>;
  location: CharacterLocation;
};

function isTauri(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

/** 订阅主窗口转发的语境。浏览器预览下降级为 DOM 事件。 */
export async function listenPetContext(
  handler: (payload: PetContextPayload) => void,
): Promise<() => void> {
  if (!isTauri()) {
    const onDemo = (event: Event) => {
      const detail = (event as CustomEvent<PetContextPayload>).detail;
      if (detail) handler(detail);
    };
    window.addEventListener('xy:pet-context', onDemo);
    return () => window.removeEventListener('xy:pet-context', onDemo);
  }
  const {listen} = await import('@tauri-apps/api/event');
  return listen<PetContextPayload>('xy:pet-context', event => handler(event.payload));
}

export async function invokePet<T>(
  command: string,
  args?: Record<string, unknown>,
): Promise<T | null> {
  if (!isTauri()) return null;
  const {invoke} = await import('@tauri-apps/api/core');
  return invoke<T>(command, args);
}

export async function fetchPetContext(): Promise<PetContextPayload | null> {
  if (!isTauri()) return null;
  return invokePet<PetContextPayload>('pet_get_context');
}

/** 主窗口退出前关闭独立的桌面宠物窗口。 */
export async function closePetWindow(): Promise<void> {
  await invokePet('pet_close');
}

/** 将当前语境投影从主窗口转发给宠物窗口。 */
export async function forwardContextToPet(payload: PetContextPayload): Promise<void> {
  if (!isTauri()) return;
  await invokePet('pet_set_context', {payload});
}
