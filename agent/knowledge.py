"""Distilled, code-verified Celeste facts for planner prompts.

Source: kb/speedrun/player_physics.md, mechanics.md and entities.md, whose
entries are marked as verified against decompiled game code.

Two blocks, injected at different points:

``MOVEMENT_REFERENCE``
    Always sent. The arc numbers a plan is built from -- distances, speeds,
    frame counts -- in one compact block, because the model cannot be asked to
    derive them and gets them wrong when it tries. Room 7 cost a round of
    rework to "jump is 32 px" when it is 27.

``mechanisms_reference(types)``
    Sent per room, for the mechanics that room actually contains. Spikes,
    springs and crumble platforms each have a rule that changes the plan (a
    spike only kills when you move into it; a spring refills the dash), and
    sending all of them every time would bury the arc numbers.

A wrong number here is worse than no number: the plan is built on it and the
failure shows up as a death rather than as a bad prompt. Keep this file short
and keep it checkable.
"""

MOVEMENT_REFERENCE = """
Coordinates: y increases downward (negative y is up). Player position is the
bottom-center of the collision box, whole pixels. One frame is one 60 Hz logic
update.

RUN. Max 90 px/s. Ground accel 1000 px/s^2 (16.667/frame): 6 frames to full
speed or to a stop. In air the same input is multiplied by 0.65 (10.833/frame).
Holding the same direction above 90 decays at 400 px/s^2 (6.667/frame) on the
ground, 10.833/frame in air.

JUMP. Takeoff vy = -105, plus +40 horizontal boost in the direction held at
takeoff. Variable jump: while jump is held, vy is clamped to -105 for the first
12 frames (0.2 s); a 1-frame tap reaches about 7 px, the full hold about 27 px.
Gravity 900 px/s^2 (15/frame), halved while |vy| < 40 and jump is held. Fall
speed caps at 160 px/s, or 240 while down is held. Coyote time 6 frames after
leaving the ground; a jump pressed up to 5 frames early still fires.

DASH. 240 px/s along the unit direction, for 10 frames after 3 freeze frames
(freeze frames do not advance the room). A straight dash covers 40 px, a
diagonal 28.28 px per axis. Exit speed: horizontal (160, 0); up (0, -120);
up-diagonal (113.14, -84.85) per axis; down directions keep their speed.
Cooldown 0.2 s between dash starts; the next dash is possible on frame 16.
Dashes refill only while grounded, from the 7th normal frame after the dash
began -- landing earlier still qualifies, standing still does not.

WALL. Walljump is (130, -105) away from the wall; it works with a gap of up to
2 px, and forces the horizontal input away for 0.16 s. Wallbounce (a jump
pressed against the wall right after a dash) is (170, -160) and works with a
gap of up to 4 px; it is the only way to gain both height and distance.
Climb: up to 45 px/s, stamina 110, climbing up costs 45.45/s; a climbjump costs
27.5 in the air, a walljump costs nothing. Wall slide starts at 20 px/s and
ramps to 160 over 1.2 s.

PLATFORM BOOST. Jumping off a moving solid adds its liftboost: horizontal
clamped to +-250, vertical only the upward part and not below -130.
""".strip()


# One entry per mechanic, keyed by the substring a bridge entity type contains.
# ``hint`` is the line the planner reads; ``types`` are the type names that
# turn it on. Only the mechanics a room actually has are sent.
MECHANICS: dict[str, dict] = {
    "spikes": {
        "types": ("Spikes",),
        "hint": (
            "SPIKES. The hitbox is only 3 px thick along the base, and it kills "
            "only while moving into it: upward spikes kill when vy >= 0, "
            "downward when vy <= 0, left-facing when vx >= 0, right-facing when "
            "vx <= 0. Moving away from the points passes through unharmed, which "
            "is how a dash carries her past a spike she started next to. "
            "Standing while overlapping any spike cancels the dash refill for "
            "that frame."),
    },
    "spring": {
        "types": ("Spring",),
        "hint": (
            "SPRING. A floor spring sets (0, -185) and refills dashes and "
            "stamina; it fires only while vy >= 0, so falling onto it is the "
            "point. A wall spring sets (+-240, -140) and forces the horizontal "
            "input in that direction for 18 frames. -185 rises about 1.8x as "
            "high as a jump (-105 tops out at 27 px)."),
    },
    "refill": {
        "types": ("Refill",),
        "hint": (
            "REFILL. Touching a crystal while dashes are missing or stamina is "
            "low restores them and the crystal disappears for 2.5 s (150 "
            "frames) before coming back."),
    },
    "crumble": {
        "types": ("CrumblePlatform",),
        "hint": (
            "CRUMBLE. Standing on it starts a 0.2 s shake; it breaks after 0.6 s "
            "at the latest (13-37 frames from the touch), then is gone for 2 s. "
            "It is solid and refills dashes until it breaks: land, jump again "
            "immediately, do not wait."),
    },
    "falling_block": {
        "types": ("FallingBlock",),
        "hint": (
            "FALLING BLOCK. Standing on it, grabbing its side, or a spring on "
            "top of it starts it: 0.2 s of shake, then it falls unless she is "
            "still riding it 0.6 s later. It falls at up to 160 px/s, carries "
            "her down, and becomes permanent ground once it lands on terrain."),
    },
    "zip_mover": {
        "types": ("ZipMover",),
        "hint": (
            "ZIP MOVER. Triggered by standing on it or grabbing its side while "
            "it rests at the start. 6 frames of shake, 30 frames to the far end "
            "(accelerating), 30 frames stopped, 120 frames back. Jump within ~10 "
            "frames of it stopping to inherit its speed (up to +-250 px/s "
            "horizontal, up to -130 vertical)."),
    },
    "dash_block": {
        "types": ("DashBlock",),
        "hint": (
            "DASH BLOCK. A dash into it breaks it and rebounds her: (-120 x "
            "direction, -120) horizontally, (0, -120) vertically. The dash is "
            "spent, not refilled."),
    },
    "dream_block": {
        "types": ("DreamBlock",),
        "hint": (
            "DREAM BLOCK. Dashing into it carries her through at 240 px/s, "
            "ignoring collision; on exit dashes and stamina refill and 3 freeze "
            "frames pass. Without a dash, or after the dash attack window, it is "
            "an ordinary solid."),
    },
    "jumpthru": {
        "types": ("JumpThru",),
        "hint": (
            "ONE-WAY PLATFORM. Jump up through it, stand on it; she cannot press "
            "down to drop through. A dash that clips its edge is nudged up onto "
            "it (up to 6 px)."),
    },
    "fake_wall": {
        "types": ("FakeWall",),
        "hint": (
            "FAKE WALL. Looks solid, is not: the tile map says solid but the "
            "collision probe says otherwise. Walking into it is how a hidden "
            "passage is found."),
    },
    "crusher": {
        "types": ("IntroCrusher",),
        "hint": (
            "CRUSHER. Triggers when her x enters [left + 30, right + 8], shakes "
            "up to 1.2 s, then moves to its target in 30 frames, accelerating. "
            "It pushes and crushes; do not be under it when it arrives."),
    },
    "cassette": {
        "types": ("CassetteBlock",),
        "hint": (
            "CASSETTE BLOCK. Toggles solid/ghost every 8 beats (1.333 s at the "
            "default tempo); the block about to change nudges 1 px as a warning. "
            "If it would close on her, it pushes her up to 4 px first, and stays "
            "open for that frame if it cannot."),
    },
}


def mechanisms_reference(types) -> str:
    """The mechanic hints that apply to a room, from its entity type names.

    Matching is by substring on the bridge's type name, so an unknown subtype
    degrades to no hint rather than to a wrong one.
    """
    joined = " ".join(sorted({str(name) for name in types or ()}))
    picked = [entry["hint"] for entry in MECHANICS.values()
              if any(name in joined for name in entry["types"])]
    return "\n\n".join(picked)
