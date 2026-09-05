import {PetScene} from '@/pet/PetScene';
import {usePetRuntime} from '@/pet/usePetRuntime';

export function SidebarPetDock({onExtract}: {onExtract: () => void | Promise<void>}) {
  const {enabled, reducedMotion, loaded, loadError, state} = usePetRuntime();

  if (!enabled) return null;

  return (
    <div className="xy-sidebar-pet-dock" data-pet-dock="sidebar" aria-label="侧边栏桌宠">
      {loadError ? (
        <div className="xy-sidebar-pet-dock__status" role="status">
          桌宠加载失败
        </div>
      ) : loaded ? (
        <PetScene
          loaded={loaded}
          state={state}
          location="island"
          reducedMotion={reducedMotion}
          placement="sidebar"
          onExtract={onExtract}
        />
      ) : (
        <div className="xy-sidebar-pet-dock__status" role="status">
          正在加载桌宠…
        </div>
      )}
    </div>
  );
}
