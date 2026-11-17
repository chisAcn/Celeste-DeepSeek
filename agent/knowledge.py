"""Distilled, code-verified Celeste movement facts for planner prompts.

Source: kb/speedrun/player_physics.md and kb/speedrun/mechanics.md, whose
entries are marked as verified against decompiled game code. Keep this file
short: the reference is injected into every LLM planning request.
"""

MOVEMENT_REFERENCE = """
Coordinates: y increases downward (negative y is up). Player position is the
bottom-center of the collision box. One frame is one 60 Hz logic update.
Run: max 90 px/s. Ground accel/decel 16.667 px/s per frame (6 frames still to
full or to stop). Air accel 10.833 per frame; speed above 90 decays 10.833 per
frame in air and 6.667 per frame on ground while holding the same direction.
Jump: takeoff vy=-105 plus +40 horizontal boost in the held direction. Holding
jump up to 12 frames sustains vy=-105 (max height about 27 px); a 1-frame tap
reaches about 7 px. Gravity adds 15 px/s per frame, halved while |vy|<40 and
jump is held. Max fall speed 160 px/s (240 while holding down).
Timing leniency: 5 frames of coyote time after leaving ground; jump input
buffers 5 frames.
Dash: 240 px/s (169.71 per axis diagonally) for 10 frames, covering 40 px
straight or 28.28 px per axis diagonally, after 3 freeze frames; full cycle
15 frames and the next dash is possible on frame 16. End speed after the
dash: horizontal -> (160,0); up -> (0,-120); up-diagonal -> (113.14,-84.85)
per axis; down directions keep their speed. Dashes refill only while grounded,
starting from the 7th normal frame after the dash began.
Walljump: (130,-105) away from the wall. Climb: up to -45 px/s, stamina 110;
climbing up drains 45.45/s (tired below 20, about 119 frames of climbing),
climbjump costs 27.5 while airborne, walljump costs nothing.
""".strip()
