"""Turn a stream of recorded input events into editable macro steps."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .keys import MODIFIER_ORDER, MODIFIERS, format_combo
from .models import Step

# Events: kind is one of mouse_down, mouse_up, scroll, key_down, key_up, move.
# ``t`` is seconds from any fixed origin; x/y are screen coordinates.


@dataclass
class RawEvent:
    t: float
    kind: str
    x: int = 0
    y: int = 0
    button: str = ""
    key: str = ""
    amount: int = 0
    horizontal: bool = False


@dataclass
class RecordOptions:
    min_wait_ms: int = 10
    click_max_ms: int = 400
    double_click_ms: int = 450
    click_slop_px: int = 4
    hold_threshold_ms: int = 600
    record_moves: bool = False
    move_sample_ms: int = 40
    merge_text: bool = False
    # Converts screen coordinates to the stored coordinate space (for
    # background targets). Returns (x, y, child, cx, cy).
    transform: Callable[[int, int], tuple[int, int, int, int, int]] | None = None
    drop_keys: tuple[str, ...] = ()


@dataclass
class _Timed:
    t: float
    step: Step
    end: float = 0.0
    extra: dict = field(default_factory=dict)


def _pos(ev: RawEvent, opts: RecordOptions) -> dict:
    if opts.transform is not None:
        x, y, child, cx, cy = opts.transform(ev.x, ev.y)
        return {"at": "point", "x": x, "y": y, "child": child, "cx": cx, "cy": cy}
    return {"at": "point", "x": ev.x, "y": ev.y}


def events_to_steps(events: list[RawEvent], opts: RecordOptions | None = None) -> list[Step]:
    opts = opts or RecordOptions()
    events = sorted(
        (e for e in events if not (e.kind in ("key_down", "key_up") and e.key in opts.drop_keys)),
        key=lambda e: e.t,
    )
    timed = _pair_events(events, opts)
    timed = _merge_double_clicks(timed, opts)
    if opts.merge_text:
        timed = _merge_text(timed)
    return _insert_waits(timed, opts)


def _pair_events(events: list[RawEvent], opts: RecordOptions) -> list[_Timed]:
    out: list[_Timed] = []
    pending_buttons: dict[str, tuple[RawEvent, _Timed]] = {}
    held_mods: list[str] = []
    pending_keys: dict[str, tuple[RawEvent, _Timed]] = {}
    mod_used: dict[str, bool] = {}
    last_move_t = -1e9

    for ev in events:
        if ev.kind == "move":
            if opts.record_moves and (ev.t - last_move_t) * 1000 >= opts.move_sample_ms:
                p = _pos(ev, opts)
                out.append(_Timed(ev.t, Step.new("move", x=p["x"], y=p["y"])))
                last_move_t = ev.t
            continue

        if ev.kind == "mouse_down":
            entry = _Timed(ev.t, Step.new("mouse_down", button=ev.button, **_pos(ev, opts)))
            out.append(entry)
            pending_buttons[ev.button] = (ev, entry)
            continue

        if ev.kind == "mouse_up":
            start = pending_buttons.pop(ev.button, None)
            if start is not None:
                down_ev, entry = start
                quick = (ev.t - down_ev.t) * 1000 <= opts.click_max_ms
                still = abs(ev.x - down_ev.x) <= opts.click_slop_px and abs(ev.y - down_ev.y) <= opts.click_slop_px
                if quick and still:
                    entry.step = Step.new("click", button=ev.button, count=1, **_pos(down_ev, opts))
                    entry.end = ev.t
                    continue
            out.append(_Timed(ev.t, Step.new("mouse_up", button=ev.button, **_pos(ev, opts))))
            continue

        if ev.kind == "scroll":
            prev = out[-1] if out else None
            if (prev is not None and prev.step.type == "scroll" and (ev.t - max(prev.t, prev.end)) < 0.25
                    and prev.step.get("horizontal") == ev.horizontal
                    and abs(prev.extra.get("x", 0) - ev.x) <= opts.click_slop_px
                    and abs(prev.extra.get("y", 0) - ev.y) <= opts.click_slop_px
                    and (prev.step.get("amount") > 0) == (ev.amount > 0)):
                prev.step.params["amount"] = max(-1000, min(1000, prev.step.get("amount") + ev.amount))
                prev.end = ev.t
                continue
            out.append(_Timed(ev.t, Step.new("scroll", amount=ev.amount, horizontal=ev.horizontal,
                                             **_pos(ev, opts)), extra={"x": ev.x, "y": ev.y}))
            continue

        if ev.kind == "key_down":
            if ev.key in pending_keys or ev.key in held_mods:
                continue  # OS auto-repeat
            if ev.key in MODIFIERS:
                held_mods.append(ev.key)
                mod_used[ev.key] = False
                entry = _Timed(ev.t, Step.new("key_down", combo=ev.key))
                out.append(entry)
                pending_keys[ev.key] = (ev, entry)
                continue
            for m in held_mods:
                mod_used[m] = True
            mods = sorted(held_mods, key=MODIFIER_ORDER.get)
            combo = format_combo((*mods, ev.key))
            entry = _Timed(ev.t, Step.new("key_down", combo=ev.key), extra={"combo": combo})
            out.append(entry)
            pending_keys[ev.key] = (ev, entry)
            continue

        if ev.kind == "key_up":
            start = pending_keys.pop(ev.key, None)
            if ev.key in held_mods:
                held_mods.remove(ev.key)
            if start is None:
                continue
            down_ev, entry = start
            held_ms = (ev.t - down_ev.t) * 1000
            if ev.key in MODIFIERS:
                used = mod_used.pop(ev.key, False)
                if not used and held_ms < opts.hold_threshold_ms:
                    entry.step = Step.new("key", combo=ev.key, hold_ms=_press_ms(held_ms))
                    entry.end = ev.t
                else:
                    out.append(_Timed(ev.t, Step.new("key_up", combo=ev.key)))
                continue
            if held_ms < opts.hold_threshold_ms:
                combo = entry.extra.get("combo", ev.key)
                entry.step = Step.new("key", combo=combo, hold_ms=_press_ms(held_ms))
                entry.end = ev.t
                # The modifiers are part of the combo now; drop their
                # separate down/up records if nothing else used them.
                entry.extra["absorbs"] = combo.split("+")[:-1]
            else:
                out.append(_Timed(ev.t, Step.new("key_up", combo=ev.key)))

    return _absorb_modifiers(out)


def _press_ms(held_ms: float) -> int:
    # Keep the real press length, but never so short that a game could miss it.
    return max(10, min(60_000, round(held_ms)))


def _absorb_modifiers(items: list[_Timed]) -> list[_Timed]:
    """Remove modifier down/up records that became part of a combo tap."""
    result = list(items)
    for i, item in enumerate(items):
        mods = item.extra.get("absorbs")
        if not mods or item.step.type != "key":
            continue
        for mod in mods:
            down = next((j for j in range(i - 1, -1, -1)
                         if result[j] is not None and result[j].step.type == "key_down"
                         and result[j].step.get("combo") == mod), None)
            up = next((j for j in range(i + 1, len(items))
                       if result[j] is not None and result[j].step.type == "key_up"
                       and result[j].step.get("combo") == mod), None)
            if down is None or up is None:
                continue
            between = [result[j] for j in range(down + 1, up) if result[j] is not None and j != i]
            if all(b.step.type in ("key_down", "key_up") and b.step.get("combo") in MODIFIERS for b in between):
                result[down] = None
                result[up] = None
    return [r for r in result if r is not None]


def _merge_double_clicks(items: list[_Timed], opts: RecordOptions) -> list[_Timed]:
    out: list[_Timed] = []
    for item in items:
        prev = out[-1] if out else None
        if (prev is not None and item.step.type == "click" and prev.step.type == "click"
                and prev.step.get("button") == item.step.get("button")
                and prev.step.get("count") < 3
                and (item.t - max(prev.t, prev.end)) * 1000 <= opts.double_click_ms
                and abs(prev.step.get("x") - item.step.get("x")) <= opts.click_slop_px
                and abs(prev.step.get("y") - item.step.get("y")) <= opts.click_slop_px):
            prev.step.params["count"] = prev.step.get("count") + 1
            prev.end = item.end or item.t
            continue
        out.append(item)
    return out


def _merge_text(items: list[_Timed]) -> list[_Timed]:
    out: list[_Timed] = []
    for item in items:
        ch = _printable(item.step)
        prev = out[-1] if out else None
        if ch is not None and prev is not None and prev.step.type == "text" \
                and (item.t - max(prev.t, prev.end)) < 1.0:
            prev.step.params["text"] = prev.step.get("text") + ch
            prev.end = item.end or item.t
            continue
        if ch is not None:
            out.append(_Timed(item.t, Step.new("text", text=ch), end=item.end))
            continue
        out.append(item)
    return out


def _printable(step: Step) -> str | None:
    if step.type != "key":
        return None
    combo = step.get("combo")
    if combo == "space":
        return " "
    if len(combo) == 1:
        return combo
    if combo.startswith("shift+") and len(combo) == 7 and combo[-1].isalpha():
        return combo[-1].upper()
    return None


def _insert_waits(items: list[_Timed], opts: RecordOptions) -> list[Step]:
    steps: list[Step] = []
    last = None
    for item in items:
        if last is not None:
            gap_ms = round((item.t - last) * 1000)
            if gap_ms >= opts.min_wait_ms:
                steps.append(Step.new("wait", ms=gap_ms))
        steps.append(item.step)
        last = max(item.t, item.end)
    return steps
