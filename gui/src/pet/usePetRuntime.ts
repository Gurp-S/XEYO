import {useEffect, useState} from 'react';
import {loadSelectedPet} from '@/pet/core/PetCatalog';
import {stateForPetContext} from '@/pet/core/PetStateBridge';
import type {LoadedPetManifest} from '@/pet/core/types';
import {useSettingsStore} from '@/stores/settingsStore';
import {fetchPetContext, listenPetContext, type PetContextPayload} from '@/pet/PetBridge';
import type {CharacterLocation} from '@/pasture/core/ContextIslandState';

export type PetRuntime = {
  enabled: boolean;
  hydrated: boolean;
  reducedMotion: boolean;
  loaded: LoadedPetManifest | null;
  loadError: string | null;
  state: string;
  location: CharacterLocation;
};

export function usePetRuntime(): PetRuntime {
  const enabled = useSettingsStore(s => s.xeyoPetEnabled !== false);
  const hydrated = useSettingsStore(s => s.hydrated);
  const selectedId = useSettingsStore(s => s.xeyoPetId);
  const reducedMotion = useSettingsStore(s => s.xeyoPetReducedMotion === true);
  const hydrate = useSettingsStore(s => s.hydrate);
  const [loaded, setLoaded] = useState<LoadedPetManifest | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [state, setState] = useState('idle');
  const [location, setLocation] = useState<CharacterLocation>('desktop');

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  useEffect(() => {
    let disposed = false;
    setLoaded(null);
    setLoadError(null);
    void loadSelectedPet(selectedId)
      .then(next => {
        if (!disposed) setLoaded(next);
      })
      .catch(error => {
        if (!disposed) {
          setLoadError(error instanceof Error ? error.message : String(error));
        }
      });
    return () => {
      disposed = true;
    };
  }, [selectedId]);

  useEffect(() => {
    let disposed = false;
    let unlisten: (() => void) | undefined;

    const apply = (payload: PetContextPayload) => {
      if (disposed) return;
      setLocation(payload.location ?? 'desktop');
      setState(stateForPetContext(payload));
    };

    void (async () => {
      const current = await fetchPetContext();
      if (!disposed && current) apply(current);
      if (!disposed) unlisten = await listenPetContext(apply);
    })();

    return () => {
      disposed = true;
      unlisten?.();
    };
  }, []);

  return {enabled, hydrated, reducedMotion, loaded, loadError, state, location};
}
