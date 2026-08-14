(() => {
  "use strict";

  const root = document.querySelector("[data-focus-timer]");
  if (!root) {
    return;
  }

  const STORAGE_KEY = "home-panel.focus-timer.v1";
  const STORAGE_VERSION = 1;
  const MIN_MINUTES = 1;
  const MAX_MINUTES = 1440;
  const RESTORE_TOLERANCE_SECONDS = 1;

  const minutesInput = document.getElementById("time-minutes");
  const display = root.querySelector("[data-timer-display]");
  const statusText = root.querySelector("[data-timer-status]");
  const startButton = root.querySelector("[data-timer-start]");
  const pauseButton = root.querySelector("[data-timer-pause]");
  const resumeButton = root.querySelector("[data-timer-resume]");
  const resetButton = root.querySelector("[data-timer-reset]");
  const presetButtons = root.querySelectorAll("[data-timer-preset]");

  if (
    !(minutesInput instanceof HTMLInputElement) ||
    !(display instanceof HTMLElement) ||
    !(statusText instanceof HTMLElement) ||
    !(startButton instanceof HTMLButtonElement) ||
    !(pauseButton instanceof HTMLButtonElement) ||
    !(resumeButton instanceof HTMLButtonElement) ||
    !(resetButton instanceof HTMLButtonElement)
  ) {
    return;
  }

  let timerState = {
    status: "idle",
    timerId: null,
    durationMinutes: null,
    remainingSeconds: null,
    endAtMs: null,
  };
  let timerIntervalId = null;

  const isValidDuration = (value) =>
    Number.isInteger(value) && value >= MIN_MINUTES && value <= MAX_MINUTES;

  const isValidTimerId = (value) =>
    typeof value === "string" && value.length >= 1 && value.length <= 100;

  const createTimerId = () => {
    if (
      typeof window.crypto === "object" &&
      window.crypto !== null &&
      typeof window.crypto.randomUUID === "function"
    ) {
      return window.crypto.randomUUID();
    }

    return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  };

  const readDurationInput = () => {
    const rawValue = minutesInput.value.trim();
    if (!/^\d+$/.test(rawValue)) {
      return null;
    }

    const minutes = Number(rawValue);
    return isValidDuration(minutes) ? minutes : null;
  };

  const formatDuration = (seconds) => {
    const normalizedSeconds = Math.max(0, Math.floor(seconds));
    const hours = Math.floor(normalizedSeconds / 3600);
    const minutes = Math.floor((normalizedSeconds % 3600) / 60);
    const remainingSeconds = normalizedSeconds % 60;

    if (hours > 0) {
      return [hours, minutes, remainingSeconds]
        .map((part) => String(part).padStart(2, "0"))
        .join(":");
    }

    return [minutes, remainingSeconds]
      .map((part) => String(part).padStart(2, "0"))
      .join(":");
  };

  const clearTicker = () => {
    if (timerIntervalId !== null) {
      window.clearInterval(timerIntervalId);
      timerIntervalId = null;
    }
  };

  const removeStoredStateIfUnchanged = (expectedRawValue) => {
    try {
      if (window.localStorage.getItem(STORAGE_KEY) === expectedRawValue) {
        window.localStorage.removeItem(STORAGE_KEY);
      }
    } catch (_error) {
      // localStorageを利用できない環境でもタイマー自体は継続する。
    }
  };

  const removeStoredStateIfOwned = (timerId) => {
    if (!isValidTimerId(timerId)) {
      return;
    }

    try {
      const rawValue = window.localStorage.getItem(STORAGE_KEY);
      if (rawValue === null) {
        return;
      }

      const parsed = JSON.parse(rawValue);
      if (
        typeof parsed === "object" &&
        parsed !== null &&
        parsed.timerId === timerId
      ) {
        window.localStorage.removeItem(STORAGE_KEY);
      }
    } catch (_error) {
      // 別タブの状態か壊れた値か判別できない場合は削除しない。
    }
  };

  const storedStateIsOwnedBy = (timerId) => {
    if (!isValidTimerId(timerId)) {
      return false;
    }

    try {
      const rawValue = window.localStorage.getItem(STORAGE_KEY);
      if (rawValue === null) {
        return false;
      }

      const parsed = JSON.parse(rawValue);
      return (
        typeof parsed === "object" &&
        parsed !== null &&
        parsed.timerId === timerId
      );
    } catch (_error) {
      return false;
    }
  };

  const serializeState = () => {
    if (timerState.status === "running") {
      return {
        version: STORAGE_VERSION,
        status: "running",
        timerId: timerState.timerId,
        durationMinutes: timerState.durationMinutes,
        endAtMs: timerState.endAtMs,
      };
    }

    if (timerState.status === "paused") {
      return {
        version: STORAGE_VERSION,
        status: "paused",
        timerId: timerState.timerId,
        durationMinutes: timerState.durationMinutes,
        remainingSeconds: timerState.remainingSeconds,
      };
    }

    return null;
  };

  const persistState = ({ allowReplace = false } = {}) => {
    const payload = serializeState();
    if (payload === null || !isValidTimerId(payload.timerId)) {
      return false;
    }

    try {
      if (!allowReplace && !storedStateIsOwnedBy(payload.timerId)) {
        return false;
      }

      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
      return true;
    } catch (_error) {
      // 保存できなくても現在ページ内のタイマー動作は継続する。
      return false;
    }
  };

  const remainingSecondsForRunningState = () => {
    if (
      timerState.status !== "running" ||
      typeof timerState.endAtMs !== "number" ||
      !isValidDuration(timerState.durationMinutes)
    ) {
      return 0;
    }

    const calculatedSeconds = Math.max(
      0,
      Math.ceil((timerState.endAtMs - Date.now()) / 1000)
    );
    const maximumSeconds = timerState.durationMinutes * 60;
    const previousSeconds = Number.isInteger(timerState.remainingSeconds)
      ? timerState.remainingSeconds
      : maximumSeconds;
    const boundedSeconds = Math.min(
      calculatedSeconds,
      maximumSeconds,
      previousSeconds
    );

    timerState.remainingSeconds = boundedSeconds;
    return boundedSeconds;
  };

  const render = () => {
    let remainingSeconds = 0;

    if (timerState.status === "running") {
      remainingSeconds = remainingSecondsForRunningState();
    } else if (timerState.status === "paused") {
      remainingSeconds = timerState.remainingSeconds ?? 0;
    } else if (timerState.status === "completed") {
      remainingSeconds = 0;
    } else {
      const previewMinutes = readDurationInput();
      display.textContent = previewMinutes === null ? "--:--" : formatDuration(previewMinutes * 60);
    }

    if (timerState.status !== "idle") {
      display.textContent = formatDuration(remainingSeconds);
    }

    startButton.hidden = timerState.status === "running" || timerState.status === "paused";
    pauseButton.hidden = timerState.status !== "running";
    resumeButton.hidden = timerState.status !== "paused";
    resetButton.hidden = timerState.status === "idle";
  };

  const setStatus = (message, isError = false) => {
    statusText.textContent = message;
    statusText.classList.toggle("focus-timer-status-error", isError);
  };

  const completeTimer = () => {
    clearTicker();
    const completedMinutes = timerState.durationMinutes;
    const completedTimerId = timerState.timerId;

    if (isValidDuration(completedMinutes)) {
      minutesInput.value = String(completedMinutes);
    }

    timerState = {
      status: "completed",
      timerId: completedTimerId,
      durationMinutes: completedMinutes,
      remainingSeconds: 0,
      endAtMs: null,
    };
    removeStoredStateIfOwned(completedTimerId);
    render();
    setStatus(
      isValidDuration(completedMinutes)
        ? `タイマーが完了しました。${completedMinutes}分を記録フォームへ反映しました。内容を確認して追加してください。`
        : "タイマーが完了しました。"
    );
  };

  const tick = () => {
    if (timerState.status !== "running") {
      return;
    }

    if (remainingSecondsForRunningState() <= 0) {
      completeTimer();
      return;
    }

    render();
  };

  const startTicker = () => {
    clearTicker();
    timerIntervalId = window.setInterval(tick, 1000);
  };

  const startTimer = () => {
    const durationMinutes = readDurationInput();
    if (durationMinutes === null) {
      setStatus("1〜1440分の整数を入力してからタイマーを開始してください。", true);
      minutesInput.focus();
      return;
    }

    timerState = {
      status: "running",
      timerId: createTimerId(),
      durationMinutes,
      remainingSeconds: durationMinutes * 60,
      endAtMs: Date.now() + durationMinutes * 60 * 1000,
    };
    persistState({ allowReplace: true });
    render();
    setStatus(`${durationMinutes}分のタイマーを開始しました。`);
    startTicker();
  };

  const pauseTimer = () => {
    if (timerState.status !== "running") {
      return;
    }

    const remainingSeconds = remainingSecondsForRunningState();
    if (remainingSeconds <= 0) {
      completeTimer();
      return;
    }

    clearTicker();
    timerState = {
      status: "paused",
      timerId: timerState.timerId,
      durationMinutes: timerState.durationMinutes,
      remainingSeconds,
      endAtMs: null,
    };
    const persisted = persistState();
    render();
    setStatus(
      persisted
        ? "タイマーを一時停止しました。"
        : "タイマーを一時停止しました。別タブの新しいタイマー状態は変更していません。"
    );
  };

  const resumeTimer = () => {
    if (
      timerState.status !== "paused" ||
      !isValidTimerId(timerState.timerId) ||
      !isValidDuration(timerState.durationMinutes) ||
      !Number.isInteger(timerState.remainingSeconds) ||
      timerState.remainingSeconds <= 0
    ) {
      return;
    }

    timerState = {
      status: "running",
      timerId: timerState.timerId,
      durationMinutes: timerState.durationMinutes,
      remainingSeconds: timerState.remainingSeconds,
      endAtMs: Date.now() + timerState.remainingSeconds * 1000,
    };
    const persisted = persistState();
    render();
    setStatus(
      persisted
        ? "タイマーを再開しました。"
        : "タイマーを再開しました。別タブの新しいタイマー状態は変更していません。"
    );
    startTicker();
  };

  const resetTimer = () => {
    clearTicker();
    const resetTimerId = timerState.timerId;
    timerState = {
      status: "idle",
      timerId: null,
      durationMinutes: null,
      remainingSeconds: null,
      endAtMs: null,
    };
    removeStoredStateIfOwned(resetTimerId);
    render();
    setStatus("タイマーをリセットしました。");
  };

  const restoreTimer = () => {
    let rawValue;
    let parsed;
    try {
      rawValue = window.localStorage.getItem(STORAGE_KEY);
      if (rawValue === null) {
        return false;
      }
      parsed = JSON.parse(rawValue);
    } catch (_error) {
      if (typeof rawValue === "string") {
        removeStoredStateIfUnchanged(rawValue);
      }
      return false;
    }

    if (
      typeof parsed !== "object" ||
      parsed === null ||
      parsed.version !== STORAGE_VERSION ||
      !isValidTimerId(parsed.timerId) ||
      !isValidDuration(parsed.durationMinutes)
    ) {
      removeStoredStateIfUnchanged(rawValue);
      return false;
    }

    if (
      parsed.status === "running" &&
      typeof parsed.endAtMs === "number" &&
      Number.isFinite(parsed.endAtMs)
    ) {
      const remainingSeconds = Math.ceil((parsed.endAtMs - Date.now()) / 1000);
      const maximumRemainingSeconds =
        parsed.durationMinutes * 60 + RESTORE_TOLERANCE_SECONDS;

      if (remainingSeconds > maximumRemainingSeconds) {
        removeStoredStateIfUnchanged(rawValue);
        return false;
      }

      timerState = {
        status: "running",
        timerId: parsed.timerId,
        durationMinutes: parsed.durationMinutes,
        remainingSeconds: Math.min(
          Math.max(remainingSeconds, 0),
          parsed.durationMinutes * 60
        ),
        endAtMs: parsed.endAtMs,
      };

      if (remainingSeconds <= 0) {
        completeTimer();
      } else {
        render();
        setStatus(`${parsed.durationMinutes}分のタイマーを復元しました。`);
        startTicker();
      }
      return true;
    }

    if (
      parsed.status === "paused" &&
      Number.isInteger(parsed.remainingSeconds) &&
      parsed.remainingSeconds > 0 &&
      parsed.remainingSeconds <= parsed.durationMinutes * 60
    ) {
      timerState = {
        status: "paused",
        timerId: parsed.timerId,
        durationMinutes: parsed.durationMinutes,
        remainingSeconds: parsed.remainingSeconds,
        endAtMs: null,
      };
      render();
      setStatus("一時停止中のタイマーを復元しました。");
      return true;
    }

    removeStoredStateIfUnchanged(rawValue);
    return false;
  };

  presetButtons.forEach((button) => {
    if (!(button instanceof HTMLButtonElement)) {
      return;
    }

    button.addEventListener("click", () => {
      if (timerState.status === "running" || timerState.status === "paused") {
        return;
      }

      const presetMinutes = Number(button.dataset.timerPreset);
      if (!isValidDuration(presetMinutes)) {
        return;
      }

      minutesInput.value = String(presetMinutes);
      timerState = {
        status: "idle",
        timerId: null,
        durationMinutes: null,
        remainingSeconds: null,
        endAtMs: null,
      };
      render();
      setStatus(`${presetMinutes}分を選択しました。「開始」でタイマーを開始できます。`);
    });
  });

  minutesInput.addEventListener("input", () => {
    if (timerState.status === "idle" || timerState.status === "completed") {
      timerState = {
        status: "idle",
        timerId: null,
        durationMinutes: null,
        remainingSeconds: null,
        endAtMs: null,
      };
      render();
    }
  });

  startButton.addEventListener("click", startTimer);
  pauseButton.addEventListener("click", pauseTimer);
  resumeButton.addEventListener("click", resumeTimer);
  resetButton.addEventListener("click", resetTimer);

  if (!restoreTimer()) {
    render();
  }
})();
