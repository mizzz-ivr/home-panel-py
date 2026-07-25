(() => {
  const LEGACY_STORAGE_KEY = 'home-panel:dashboard-layout:v1';

  const error = document.querySelector('.error');
  if (error) {
    window.setTimeout(() => {
      error.style.transition = 'opacity 0.4s';
      error.style.opacity = '0';
    }, 4000);
  }

  const container = document.querySelector('[data-swapy-container]');
  const preferencesData = document.querySelector('#dashboard-preferences-data');
  const resetButton = document.querySelector('#reset-layout');
  const saveVisibilityButton = document.querySelector('#save-card-visibility');
  const visibilityInputs = Array.from(document.querySelectorAll('[data-card-visibility]'));
  const layoutStatus = document.querySelector('#layout-status');
  const preferencesStatus = document.querySelector('#preferences-status');

  if (!container || !preferencesData) {
    return;
  }

  const endpoint = container.dataset.preferencesEndpoint;
  const fallbackOrder = visibilityInputs.map((input) => input.value);

  const announceLayout = (message) => {
    if (layoutStatus) {
      layoutStatus.textContent = message;
    }
  };

  const announcePreferences = (message, isError = false) => {
    if (preferencesStatus) {
      preferencesStatus.textContent = message;
      preferencesStatus.classList.toggle('settings-error', isError);
    }
  };

  const isValidPreferences = (value) => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      return false;
    }
    if (!Array.isArray(value.order) || !Array.isArray(value.hidden)) {
      return false;
    }

    const order = value.order;
    const hidden = value.hidden;
    const knownIds = new Set(fallbackOrder);
    return (
      order.length === fallbackOrder.length &&
      new Set(order).size === fallbackOrder.length &&
      order.every((cardId) => knownIds.has(cardId)) &&
      hidden.length < fallbackOrder.length &&
      new Set(hidden).size === hidden.length &&
      hidden.every((cardId) => knownIds.has(cardId))
    );
  };

  let preferences;
  try {
    const parsed = JSON.parse(preferencesData.textContent || '{}');
    preferences = isValidPreferences(parsed)
      ? {
          order: [...parsed.order],
          hidden: [...parsed.hidden],
          persisted: parsed.persisted === true,
        }
      : { order: [...fallbackOrder], hidden: [], persisted: false };
  } catch (parseError) {
    console.warn('ダッシュボード設定を読み込めませんでした。', parseError);
    preferences = { order: [...fallbackOrder], hidden: [], persisted: false };
  }

  const slotIndex = (slotId) => Number.parseInt(slotId.replace('slot-', ''), 10);
  const visibleCardIds = () =>
    preferences.order.filter((cardId) => !preferences.hidden.includes(cardId));

  const applyVisibleOrder = (order) => {
    const slots = Array.from(container.querySelectorAll('[data-swapy-slot]')).sort(
      (left, right) => slotIndex(left.dataset.swapySlot) - slotIndex(right.dataset.swapySlot),
    );
    const items = new Map(
      Array.from(container.querySelectorAll('[data-swapy-item]')).map((item) => [
        item.dataset.swapyItem,
        item,
      ]),
    );

    order.forEach((cardId, index) => {
      const slot = slots[index];
      const item = items.get(cardId);
      if (slot && item) {
        slot.appendChild(item);
      }
    });
  };

  const mergeVisibleOrder = (newVisibleOrder) => {
    let visibleIndex = 0;
    return preferences.order.map((cardId) => {
      if (preferences.hidden.includes(cardId)) {
        return cardId;
      }
      const nextCardId = newVisibleOrder[visibleIndex];
      visibleIndex += 1;
      return nextCardId;
    });
  };

  const readErrorMessage = async (response) => {
    try {
      const payload = await response.json();
      return payload.detail || '設定を保存できませんでした。';
    } catch (readError) {
      return '設定を保存できませんでした。';
    }
  };

  const savePreferences = async (nextPreferences) => {
    if (!endpoint || !isValidPreferences(nextPreferences)) {
      throw new Error('保存するダッシュボード設定が不正です。');
    }

    const response = await window.fetch(endpoint, {
      method: 'PUT',
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        order: nextPreferences.order,
        hidden: nextPreferences.hidden,
      }),
    });

    if (!response.ok) {
      throw new Error(await readErrorMessage(response));
    }

    preferences = {
      order: [...nextPreferences.order],
      hidden: [...nextPreferences.hidden],
      persisted: true,
    };
  };

  const removeLegacyLayout = () => {
    try {
      window.localStorage.removeItem(LEGACY_STORAGE_KEY);
    } catch (storageError) {
      console.warn('旧カード配置を削除できませんでした。', storageError);
    }
  };

  const migrateLegacyLayout = async () => {
    if (preferences.persisted) {
      return;
    }

    try {
      const rawLayout = window.localStorage.getItem(LEGACY_STORAGE_KEY);
      if (!rawLayout) {
        return;
      }

      const layout = JSON.parse(rawLayout);
      if (!layout || typeof layout !== 'object' || Array.isArray(layout)) {
        removeLegacyLayout();
        return;
      }

      const legacyOrder = Object.entries(layout)
        .sort(([left], [right]) => slotIndex(left) - slotIndex(right))
        .map(([, cardId]) => cardId);
      const isValidLegacyOrder =
        legacyOrder.length === preferences.order.length &&
        new Set(legacyOrder).size === preferences.order.length &&
        legacyOrder.every((cardId) => preferences.order.includes(cardId));

      if (!isValidLegacyOrder) {
        removeLegacyLayout();
        return;
      }

      const migrated = { order: legacyOrder, hidden: [] };
      applyVisibleOrder(legacyOrder);
      await savePreferences(migrated);
      removeLegacyLayout();
      announceLayout('ブラウザに保存されていたカード配置をサーバーへ移行しました。');
    } catch (migrationError) {
      console.warn('旧カード配置を移行できませんでした。', migrationError);
      announceLayout('旧カード配置を移行できませんでした。既定配置で表示します。');
    }
  };

  saveVisibilityButton?.addEventListener('click', async () => {
    const visibleIds = visibilityInputs.filter((input) => input.checked).map((input) => input.value);
    if (visibleIds.length === 0) {
      announcePreferences('最低1枚のカードを表示してください。', true);
      visibilityInputs[0]?.focus();
      return;
    }

    const nextPreferences = {
      order: [...preferences.order],
      hidden: preferences.order.filter((cardId) => !visibleIds.includes(cardId)),
    };

    saveVisibilityButton.disabled = true;
    announcePreferences('表示設定を保存しています。');
    try {
      await savePreferences(nextPreferences);
      announcePreferences('表示設定を保存しました。');
      window.location.reload();
    } catch (saveError) {
      console.warn('カード表示設定を保存できませんでした。', saveError);
      announcePreferences(saveError.message, true);
      saveVisibilityButton.disabled = false;
    }
  });

  resetButton?.addEventListener('click', async () => {
    if (!endpoint) {
      return;
    }

    resetButton.disabled = true;
    announcePreferences('設定を初期化しています。');
    try {
      const response = await window.fetch(endpoint, {
        method: 'DELETE',
        credentials: 'same-origin',
        cache: 'no-store',
      });
      if (!response.ok) {
        throw new Error(await readErrorMessage(response));
      }
      removeLegacyLayout();
      announcePreferences('設定を初期化しました。');
      window.location.reload();
    } catch (resetError) {
      console.warn('ダッシュボード設定を初期化できませんでした。', resetError);
      announcePreferences(resetError.message, true);
      resetButton.disabled = false;
    }
  });

  const initialize = async () => {
    await migrateLegacyLayout();
    const currentVisibleOrder = visibleCardIds();
    applyVisibleOrder(currentVisibleOrder);

    if (currentVisibleOrder.length < 2) {
      container.classList.add('swapy-unavailable');
      announceLayout('表示カードが1枚のため、並び替えは無効です。');
      return;
    }

    if (!window.Swapy?.createSwapy) {
      container.classList.add('swapy-unavailable');
      announceLayout('並び替え機能を読み込めませんでした。通常の操作は利用できます。');
      return;
    }

    const swapy = window.Swapy.createSwapy(container, {
      animation: 'dynamic',
      swapMode: 'drop',
    });

    swapy.onSwapEnd(async (event) => {
      if (!event.hasChanged) {
        return;
      }

      const map = event.slotItemMap.asObject;
      const nextVisibleOrder = Object.entries(map)
        .sort(([left], [right]) => slotIndex(left) - slotIndex(right))
        .map(([, cardId]) => cardId);
      const expectedVisibleIds = visibleCardIds();
      const isValidVisibleOrder =
        nextVisibleOrder.length === expectedVisibleIds.length &&
        new Set(nextVisibleOrder).size === expectedVisibleIds.length &&
        nextVisibleOrder.every((cardId) => expectedVisibleIds.includes(cardId));

      if (!isValidVisibleOrder) {
        announceLayout('カード配置を検証できなかったため保存しませんでした。');
        return;
      }

      const previousOrder = [...preferences.order];
      const nextPreferences = {
        order: mergeVisibleOrder(nextVisibleOrder),
        hidden: [...preferences.hidden],
      };
      try {
        await savePreferences(nextPreferences);
        announceLayout('カードの配置をサーバーへ保存しました。');
      } catch (saveError) {
        preferences.order = previousOrder;
        console.warn('カード配置を保存できませんでした。', saveError);
        announceLayout('カードの配置を保存できませんでした。再読み込みすると元に戻ります。');
      }
    });

    window.addEventListener(
      'beforeunload',
      () => {
        swapy.destroy();
      },
      { once: true },
    );
  };

  initialize().catch((initializeError) => {
    container.classList.add('swapy-unavailable');
    console.warn('ダッシュボード設定を初期化できませんでした。', initializeError);
    announceLayout('ダッシュボード設定を初期化できませんでした。通常の操作は利用できます。');
  });
})();
