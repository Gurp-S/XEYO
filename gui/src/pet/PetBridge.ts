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

/** Subscribe to context forwarded from the main window. Falls back to a DOM event in browser preview. */
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

/** Close the independent desktop-pet window before the main window exits. */
export async function closePetWindow(): Promise<void> {
  await invokePet('pet_close');
}

/** Forward the current context projection from the main window to the pet window. */
export async function forwardContextToPet(payload: PetContextPayload): Promise<void> {
  if (!isTauri()) return;
  await invokePet('pet_set_context', {payload});
}
