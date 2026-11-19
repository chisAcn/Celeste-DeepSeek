"""What a dash actually aims with.

The bridge applies one action chunk per logic tick, and the three freeze ticks
after a dash press advance nothing: no ``Level.Update`` runs, so no chunk is
consumed and no frame is counted. The tick that reads the dash direction is
therefore the tick *after* the chunk that pressed dash -- never the pressing
chunk itself (kb/speedrun/input.md: "冲刺方向 = 冻结结束后第一帧的瞄准输入").

That makes a one-frame dash chunk a trap. ``[right+up+dash] x1`` followed by
``[right] x20`` reads like an up-right dash and is a horizontal one: the aim
frame is the 20-frame chunk, and it says right. Room 8 cost an afternoon of
"the bridge flattens air dashes" before the timeline explained it -- the bridge
was right and the chunking was wrong.

``repair`` closes the gap without asking the model to count frames: the
directions the dash chunk declared are held for one more tick, so the aim frame
carries them, and the rest of the chunk keeps its own buttons. The frame count
is preserved, so contracts, traces and ``expect`` rows stay aligned.
"""

from agent.protocol import FrameAction

DIRECTIONS = ("left", "right", "up", "down")
_DIRECTIONS = frozenset(DIRECTIONS)


def declared_aim(action: FrameAction) -> list[str]:
    """The directions this chunk asks to be aiming with, in a fixed order."""
    return [button for button in DIRECTIONS if button in action.buttons]


def audit(actions: list[FrameAction]) -> list[str]:
    """Every place the aim frame will not see the aim the dash chunk declared.

    A dash chunk that lasts several frames is not a problem: the chunk is still
    the one being applied when the freeze ends, so it aims for itself.
    """
    problems = []
    for index, action in enumerate(actions):
        if "dash" not in action.buttons or action.frames != 1:
            continue
        aim = declared_aim(action)
        if not aim:
            continue
        if index + 1 >= len(actions):
            problems.append(
                f"chunk {index + 1} presses dash as the last chunk, so nothing "
                f"covers the aim frame and the dash {aim} was never asked for")
            continue
        following = set(actions[index + 1].buttons)
        missing = [direction for direction in aim if direction not in following]
        if missing:
            problems.append(
                f"chunk {index + 1} presses dash aiming {'+'.join(aim)} but chunk "
                f"{index + 2} drops {'+'.join(missing)} on the aim frame, so the "
                f"dash goes {'+'.join(d for d in aim if d not in missing) or 'forward'}")
    return problems


def repair(actions: list[FrameAction]) -> tuple[list[FrameAction], list[str]]:
    """Hold each declared dash aim into the frame the game actually reads.

    Returns the actions to send and one note per chunk that was changed. The
    total frame count is unchanged: the following chunk donates its first frame
    to the aim and keeps the rest.
    """
    problems = audit(actions)
    if not problems:
        return list(actions), []

    fixed: list[FrameAction] = []
    notes = []
    index = 0
    while index < len(actions):
        action = actions[index]
        fixed.append(action)
        aim = declared_aim(action)
        following = actions[index + 1] if index + 1 < len(actions) else None
        holds_aim = ("dash" in action.buttons and action.frames == 1 and aim
                     and following is not None
                     and any(direction not in following.buttons for direction in aim))
        if not holds_aim:
            index += 1
            continue
        held = list(following.buttons)
        held += [direction for direction in aim if direction not in held]
        fixed.append(FrameAction(buttons=held, frames=1))
        if following.frames > 1:
            fixed.append(FrameAction(buttons=list(following.buttons),
                                     frames=following.frames - 1))
        notes.append(
            f"held {'+'.join(direction for direction in aim if direction not in following.buttons)} "
            f"for the aim frame after chunk {index + 1}")
        index += 2
    return fixed, notes
