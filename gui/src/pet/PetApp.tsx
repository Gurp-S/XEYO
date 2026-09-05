import {PetScene} from '@/pet/PetScene';
import {usePetRuntime} from '@/pet/usePetRuntime';

export function PetApp() {
  const {reducedMotion, loaded, loadError, state, location} = usePetRuntime();


  // 可见性指令由主窗口统一管理。此处绝不自行隐藏：
  // 侧栏长按后，原生窗口必须保持可见，直到其运行时完成水合。
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
