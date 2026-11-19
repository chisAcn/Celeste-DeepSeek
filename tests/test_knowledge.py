"""The knowledge a plan is built on: arc numbers always, mechanics per room.

Two failure modes are worth guarding against. Sending every mechanic every time
buries the numbers the model actually needs; sending the wrong mechanic is worse
than sending none, because the plan is built on it.
"""

from agent.knowledge import MECHANICS, MOVEMENT_REFERENCE, mechanisms_reference


def test_the_arc_numbers_are_the_calibrated_ones():
    # Room 7 cost a rework to "a jump is 32 px" when it is 27; these are the
    # numbers that would have to stay right for that not to happen again.
    assert "27 px" in MOVEMENT_REFERENCE
    assert "about 7 px" in MOVEMENT_REFERENCE
    assert "40 px" in MOVEMENT_REFERENCE  # straight dash
    assert "28.28" in MOVEMENT_REFERENCE  # diagonal dash, per axis
    assert "170, -160" in MOVEMENT_REFERENCE  # wallbounce
    assert "130, -105" in MOVEMENT_REFERENCE  # walljump


def test_no_mechanic_section_leaks_into_the_always_on_reference():
    assert "SPRING" not in MOVEMENT_REFERENCE
    assert "CRUMBLE" not in MOVEMENT_REFERENCE


def test_only_the_mechanics_in_the_room_are_sent():
    text = mechanisms_reference(["Spikes", "CrumblePlatform"])

    assert "SPIKES" in text and "CRUMBLE" in text
    assert "SPRING" not in text and "ZIP MOVER" not in text


def test_a_room_with_nothing_special_gets_nothing():
    assert mechanisms_reference(["Solid", "Player"]) == ""
    assert mechanisms_reference(None) == ""


def test_repeated_types_do_not_repeat_the_section():
    text = mechanisms_reference(["Spikes", "Spikes", "Spikes"])

    assert text.count("SPIKES.") == 1


def test_the_spike_rule_says_direction_matters_and_the_hitbox_is_thin():
    text = mechanisms_reference(["Spikes"])

    assert "3 px" in text
    assert "vy >= 0" in text and "vx <= 0" in text


def test_every_mechanic_has_a_type_and_a_hint():
    for key, entry in MECHANICS.items():
        assert entry["types"] and entry["hint"], key
        assert len(entry["hint"]) < 600, key  # the prompt is the scarce resource


def test_the_dash_aim_frame_is_spelled_out():
    # Room 8: the direction is read after the freeze, not on the press, so a
    # plan that drops it for that one frame dashes along facing instead. The
    # super/hyper pair is what a jump during that window buys.
    assert "first frame after the freeze" in MOVEMENT_REFERENCE
    assert "hold the direction past the press" in MOVEMENT_REFERENCE
    assert "(260, -105)" in MOVEMENT_REFERENCE  # super, grounded
    assert "(325, -52.5)" in MOVEMENT_REFERENCE  # hyper, ducking
