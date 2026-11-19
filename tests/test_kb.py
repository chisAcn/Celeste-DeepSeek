"""Quoting the knowledge base: what gets pulled in, and what must not.

The corpus is 145k characters. Sending it whole is the same as sending none of
it, and sending a rule without its condition is worse than sending nothing,
because the plan is built on it. So the tests are about the three properties
that make an excerpt trustworthy:

* it is a whole section, never a cut-down fragment;
* it is quoted verbatim, so a number can be traced to its line;
* it answers the room's question -- its entities and her footing -- and is
  silent otherwise.
"""

from agent.agents import Anchor, PlannerAgent
from agent.kb import (
    DEFAULT_BUDGET,
    DEFAULT_ROOT,
    KnowledgeBase,
    parse_sections,
    terms_for,
    terms_for_entities,
    terms_for_state,
)
from agent.kb import main as kb_main
from agent.protocol import GameState, PlayerState, RoomState


def ground(**motion):
    return PlayerState(x=2719.0, y=-1704.0, dashes=1, stamina=110.0, dead=False,
                       on_ground=True, vx=0.0, vy=0.0, **motion)


def air(**motion):
    return PlayerState(x=2719.0, y=-1760.0, dashes=0, stamina=40.0, dead=False,
                       on_ground=False, vx=90.0, vy=-100.0, **motion)


def state(player=None):
    return GameState(frame=0, player=player or ground(),
                     room=RoomState(name="8", completed=False))


# -- parsing ------------------------------------------------------------


def test_a_heading_with_children_is_not_a_section_of_its_own():
    text = "# doc\n\nintro\n\n## parent\n\nparent intro\n\n### child\n\nbody\n"

    assert parse_sections(text) == [("child", "body")]


def test_the_separator_rule_between_sections_is_trimmed_away():
    text = "## a\n\nbody\n\n---\n\n## b\n\nother\n"

    assert parse_sections(text) == [("a", "body"), ("b", "other")]


def test_the_real_corpus_parses_into_leaf_sections():
    kb = KnowledgeBase.load()

    assert len(kb) > 100
    for section in kb.sections:
        assert section.body
        assert "\n## " not in section.body and not section.body.startswith("#")


# -- retrieval ----------------------------------------------------------


def test_a_spiked_room_gets_the_sections_about_spikes_and_walls():
    kb = KnowledgeBase.load()

    text, labels = kb.excerpt(terms_for(["Spikes", "Spring"], ground()))

    assert any("尖刺" in label for label in labels)
    assert "wallbounce" in text.casefold()
    assert len(text) <= DEFAULT_BUDGET


def test_every_excerpt_is_a_whole_section_quoted_verbatim():
    kb = KnowledgeBase.load()
    picked = kb.search(terms_for(["Spikes", "JumpThru"], air()))

    assert picked
    for section in picked:
        source = (DEFAULT_ROOT / section.doc).read_text(encoding="utf-8")
        assert f"## {section.heading}" in source or f"### {section.heading}" in source
        assert section.body in source


def test_the_budget_is_a_hard_limit_and_a_section_is_never_cut():
    kb = KnowledgeBase.load()
    picked = kb.search(terms_for(["Spikes", "CrumblePlatform"], ground()), budget=1500)

    used = sum(len(section.block()) + 2 for section in picked)
    assert used <= 1500
    for section in picked:
        source = (DEFAULT_ROOT / section.doc).read_text(encoding="utf-8")
        assert section.body in source


def test_retrieval_is_deterministic():
    kb = KnowledgeBase.load()
    terms = terms_for(["Spikes", "Spring"], ground())

    first = [section.label for section in kb.search(terms)]
    second = [section.label for section in kb.search(terms)]

    assert first == second


def test_a_room_with_no_matching_mechanics_gets_nothing():
    kb = KnowledgeBase.load()

    assert terms_for(["Solid", "Player"], None) == ()
    assert kb.excerpt(()) == ("", ())


def test_a_missing_corpus_is_empty_not_an_error(tmp_path):
    kb = KnowledgeBase.load(tmp_path / "not-here")

    assert len(kb) == 0
    assert kb.origin == "missing"
    assert kb.excerpt(("尖刺",)) == ("", ())


# -- terms --------------------------------------------------------------


def test_entity_terms_are_the_words_the_corpus_uses():
    terms = terms_for_entities(["Spikes", "CrumblePlatform", "FallingBlock"])

    assert "尖刺" in terms and "spike" in terms
    assert "碎裂平台" in terms
    assert "坠落块" in terms
    # A type this corpus does not document degrades to nothing, not to a guess.
    assert terms_for_entities(["UnknownThing"]) == ()


def test_the_query_changes_with_her_footing():
    assert "跳跃" in terms_for_state(ground())
    assert "攀爬" not in terms_for_state(ground())
    assert "攀爬" in terms_for_state(air())
    assert terms_for_state(None) == ()


def test_the_preview_command_shows_what_a_room_would_be_sent(capsys):
    assert kb_main(["--types", "Spikes", "--budget", "1200"]) == 0

    out = capsys.readouterr().out
    assert "sections (kb)" in out
    assert ".md §" in out


def test_a_budget_too_small_for_any_section_says_so(capsys):
    assert kb_main(["--types", "Spikes", "--budget", "10"]) == 0

    assert "nothing matched" in capsys.readouterr().out


# -- the prompt ---------------------------------------------------------


def test_the_planner_quotes_the_corpus_only_when_it_is_given_one():
    anchor = Anchor(id=1, state=state(), entities=["Spikes"], still_for=0.4)

    with_kb = PlannerAgent(lambda context: None, kb=KnowledgeBase.load())
    context = with_kb.context(anchor)

    assert "movement_reference" in context
    assert context["room_knowledge"]
    assert "knowledge_guidance" in context
    assert with_kb.kb_sections >= 1

    without = PlannerAgent(lambda context: None)
    assert "room_knowledge" not in without.context(anchor)
    assert without.kb_sections == 0
