"use strict";

function createHabitUndoNotice(payload) {
  const section = document.createElement("section");
  section.className = "card habit-undo-notice";
  section.setAttribute("role", "status");

  const message = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = "直前の習慣操作を元に戻せます";
  const detail = document.createElement("p");
  detail.className = "hint";
  detail.textContent = `${payload.label}を操作前の状態へ戻します。Undoは10分間、直前の1操作だけ有効です。`;
  message.append(title, detail);

  const form = document.createElement("form");
  form.action = "/habits/completions/undo";
  form.method = "post";

  const token = document.createElement("input");
  token.type = "hidden";
  token.name = "token";
  token.value = payload.token;

  const button = document.createElement("button");
  button.type = "submit";
  button.className = "secondary-button";
  button.textContent = "元に戻す";

  form.append(token, button);
  section.append(message, form);
  return section;
}

async function loadHabitUndo(container) {
  const targetDate = container.dataset.targetDate;
  if (!targetDate) {
    return;
  }

  try {
    const response = await fetch(
      `/habits/completions/undo?target_date=${encodeURIComponent(targetDate)}`,
      {
        headers: { Accept: "application/json" },
        cache: "no-store",
      },
    );
    if (!response.ok) {
      return;
    }

    const payload = await response.json();
    if (!payload.available) {
      return;
    }

    container.replaceChildren(createHabitUndoNotice(payload));
    container.hidden = false;

    if (Number.isFinite(payload.expires_in_seconds)) {
      window.setTimeout(() => {
        container.replaceChildren();
        container.hidden = true;
      }, Math.max(0, payload.expires_in_seconds * 1000));
    }
  } catch (_error) {
    // Undo通知が取得できなくても、通常の習慣操作は継続する。
  }
}

document.querySelectorAll("[data-habit-undo]").forEach((container) => {
  loadHabitUndo(container);
});
