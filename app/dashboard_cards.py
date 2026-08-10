from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DASHBOARD_PREFERENCES_KEY = "dashboard.preferences.v1"


@dataclass(frozen=True)
class DashboardCardDefinition:
    card_id: str
    title: str
    template: str


DASHBOARD_CARDS = (
    DashboardCardDefinition("focus", "Today Focus", "cards/focus.html"),
    DashboardCardDefinition("todo", "ToDo", "cards/todo.html"),
    DashboardCardDefinition("memo", "今日のメモ", "cards/memo.html"),
    DashboardCardDefinition("time", "学習/作業時間", "cards/time.html"),
    DashboardCardDefinition("habits", "習慣トラッカー", "cards/habits.html"),
)
DASHBOARD_CARD_BY_ID = {card.card_id: card for card in DASHBOARD_CARDS}
DEFAULT_DASHBOARD_ORDER = tuple(card.card_id for card in DASHBOARD_CARDS)


@dataclass(frozen=True)
class DashboardPreferences:
    order: tuple[str, ...]
    hidden: frozenset[str]
    persisted: bool = False

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "order": list(self.order),
            "hidden": [card_id for card_id in self.order if card_id in self.hidden],
        }

    def ordered_cards(self) -> list[DashboardCardDefinition]:
        return [DASHBOARD_CARD_BY_ID[card_id] for card_id in self.order]

    def visible_cards(self) -> list[DashboardCardDefinition]:
        return [card for card in self.ordered_cards() if card.card_id not in self.hidden]


def default_dashboard_preferences(*, persisted: bool = False) -> DashboardPreferences:
    return DashboardPreferences(DEFAULT_DASHBOARD_ORDER, frozenset(), persisted=persisted)


def validate_dashboard_preferences(
    order: Any,
    hidden: Any,
    *,
    persisted: bool = True,
) -> DashboardPreferences:
    if type(order) is not list or any(type(card_id) is not str for card_id in order):
        raise ValueError("orderはカードIDの配列で指定してください。")
    if type(hidden) is not list or any(type(card_id) is not str for card_id in hidden):
        raise ValueError("hiddenはカードIDの配列で指定してください。")

    known_ids = set(DEFAULT_DASHBOARD_ORDER)
    if len(order) != len(DEFAULT_DASHBOARD_ORDER) or set(order) != known_ids:
        raise ValueError("orderには登録済みカードを重複なくすべて指定してください。")
    if len(set(order)) != len(order):
        raise ValueError("orderに同じカードIDを重複して指定できません。")

    hidden_ids = set(hidden)
    if len(hidden_ids) != len(hidden):
        raise ValueError("hiddenに同じカードIDを重複して指定できません。")
    if not hidden_ids.issubset(known_ids):
        raise ValueError("hiddenに未登録のカードIDを指定できません。")
    if len(hidden_ids) >= len(known_ids):
        raise ValueError("ダッシュボードには最低1枚のカードを表示してください。")

    return DashboardPreferences(tuple(order), frozenset(hidden_ids), persisted=persisted)


def load_dashboard_preferences(raw_value: Any) -> DashboardPreferences:
    if type(raw_value) is not dict:
        return default_dashboard_preferences()

    raw_order = raw_value.get("order")
    raw_hidden = raw_value.get("hidden", [])
    if type(raw_order) is not list or any(type(card_id) is not str for card_id in raw_order):
        return default_dashboard_preferences()
    if type(raw_hidden) is not list or any(type(card_id) is not str for card_id in raw_hidden):
        return default_dashboard_preferences()

    known_ids = set(DEFAULT_DASHBOARD_ORDER)
    normalized_order: list[str] = []
    seen: set[str] = set()
    for card_id in raw_order:
        if card_id in known_ids and card_id not in seen:
            normalized_order.append(card_id)
            seen.add(card_id)
    normalized_order.extend(card_id for card_id in DEFAULT_DASHBOARD_ORDER if card_id not in seen)

    normalized_hidden = {
        card_id for card_id in raw_hidden if card_id in known_ids
    }
    if len(normalized_hidden) >= len(known_ids):
        normalized_hidden = set()

    return DashboardPreferences(
        tuple(normalized_order),
        frozenset(normalized_hidden),
        persisted=True,
    )
