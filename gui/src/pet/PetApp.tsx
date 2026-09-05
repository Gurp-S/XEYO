import {PetScene} from '@/pet/PetScene';
import {usePetRuntime} from '@/pet/usePetRuntime';

export function PetApp() {
  const {reducedMotion, loaded, loadError, state, location} = usePetRuntime();


  // The main window owns visibility commands. Never self-hide here: after a
  // sidebar long-press, the native window must remain visible while its runtime hydrates.
  if (loadError) {
    return (
      <div className="xeyo-pet-root">
        <div className="xeyo-pet__error" role="status">
          XeyoPet 加载失败
        </div>
      </div>
    );
  }
  if (!loaded) {
    return (
      <div className="xeyo-pet-root">
        <div className="xeyo-pet__loading" role="status">
          正在加载桌宠…
        </div>
      </div>
    );
  }

  return (
    <PetScene
      loaded={loaded}
      state={state}
      location={location}
      reducedMotion={reducedMotion}
    />
  );
}
