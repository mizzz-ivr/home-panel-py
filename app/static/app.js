(() => {
  const STORAGE_KEY = 'home-panel:dashboard-layout:v1';
  const DEFAULT_LAYOUT = {
    'slot-1': 'todo',
    'slot-2': 'memo',
    'slot-3': 'time',
  };
  const SLOT_IDS = Object.keys(DEFAULT_LAYOUT);
  const ITEM_IDS = Object.values(DEFAULT_LAYOUT);

  const error = document.querySelector('.error');
  if (error) {
    window.setTimeout(() => {
      error.style.transition = 'opacity 0.4s';
      error.style.opacity = '0';
    }, 4000);
  }

  const container = document.querySelector('[data-swapy-container]');
  const resetButton = document.querySelector('#reset-layout');
  const status = document.querySelector('#layout-status');

  const announce = (message) => {
    if (status) {
      status.textContent = message;
    }
  };

  const isValidLayout = (layout) => {
    if (!layout || typeof layout !== 'object' || Array.isArray(layout)) {
      return false;
    }

    const slots = Object.keys(layout);
    const items = Object.values(layout);
    return (
      slots.length === SLOT_IDS.length &&
      SLOT_IDS.every((slotId) => slots.includes(slotId)) &&
      items.length === ITEM_IDS.length &&
      ITEM_IDS.every((itemId) => items.includes(itemId)) &&
      new Set(items).size === ITEM_IDS.length
    );
  };

  const readSavedLayout = () => {
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (!saved) {
        return DEFAULT_LAYOUT;
      }

      const parsed = JSON.parse(saved);
      if (isValidLayout(parsed)) {
        return parsed;
      }

      window.localStorage.removeItem(STORAGE_KEY);
    } catch (error) {
      console.warn('保存済みのカード配置を読み込めませんでした。', error);
    }

    return DEFAULT_LAYOUT;
  };

  const applyLayout = (layout) => {
    if (!container || !isValidLayout(layout)) {
      return;
    }

    SLOT_IDS.forEach((slotId) => {
      const slot = container.querySelector(`[data-swapy-slot="${slotId}"]`);
      const itemId = layout[slotId];
      const item = container.querySelector(`[data-swapy-item="${itemId}"]`);
      if (slot && item) {
        slot.appendChild(item);
      }
    });
  };

  const saveLayout = (layout) => {
    if (!isValidLayout(layout)) {
      return;
    }

    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
      announce('カードの配置を保存しました。');
    } catch (error) {
      console.warn('カード配置を保存できませんでした。', error);
      announce('カードの配置を保存できませんでした。');
    }
  };

  resetButton?.addEventListener('click', () => {
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch (error) {
      console.warn('カード配置を初期化できませんでした。', error);
    }
    window.location.reload();
  });

  if (!container) {
    return;
  }

  applyLayout(readSavedLayout());

  if (!window.Swapy?.createSwapy) {
    container.classList.add('swapy-unavailable');
    announce('並び替え機能を読み込めませんでした。通常の操作は利用できます。');
    return;
  }

  const swapy = window.Swapy.createSwapy(container, {
    animation: 'dynamic',
    swapMode: 'drop',
  });

  swapy.onSwapEnd((event) => {
    if (event.hasChanged) {
      saveLayout(event.slotItemMap.asObject);
    }
  });

  window.addEventListener(
    'beforeunload',
    () => {
      swapy.destroy();
    },
    { once: true },
  );
})();
