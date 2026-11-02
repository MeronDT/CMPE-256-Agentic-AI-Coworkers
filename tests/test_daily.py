from datetime import date

from coworkers.daily import rank
from coworkers.daily.graph import check_article, passed, quote_found, run_brief
from coworkers.daily.sources import in_window

AS_OF = date(2026, 11, 1)


def article(i, source=None, topic="distributed consensus replication", published="2026-10-30"):
    text = f"Article {i} explains how {topic} works in production systems. " + "Details about replicas and leaders. " * 90
    return {"url": f"https://example.com/{i}", "title": f"Post {i} on {topic}", "source": source or f"Source{i}",
            "published": published, "authority": 1.0, "snippet": text[:300], "text": text, "kind": "page"}


def fetcher(items):
    return lambda as_of: (items, ["One source was down"])


def run(stub, store, profile, items, day=AS_OF, **kwargs):
    return run_brief(stub, store, profile, day, fetch=fetcher(items), hydrate=lambda c: c,
                     check_url=lambda url: True, **kwargs)


def test_brief_has_three_verified_articles(stub, store, profile):
    brief = run(stub, store, profile, [article(i) for i in range(8)])
    assert len(brief["items"]) == 3
    assert all(i["verification"]["passed"] for i in brief["items"])
    assert len({i["source"] for i in brief["items"]}) == 3
    assert "One source was down" in brief["warnings"]
    assert brief["concepts_total"] == 3


def test_hallucinated_quote_triggers_retry(stub, store, profile):
    stub.bad_quotes_for = 1
    brief = run(stub, store, profile, [article(i) for i in range(8)])
    assert len(brief["items"]) == 3
    assert max(brief["attempts"].values()) == 2


def test_article_that_keeps_failing_is_replaced(stub, store, profile):
    # All three fail the first round, then the first article fails its retry too.
    stub.bad_quotes_for = 4
    brief = run(stub, store, profile, [article(i) for i in range(8)])
    assert len(brief["items"]) == 3
    assert len(brief["rejected"]) == 1
    assert brief["rejected"][0] not in {i["url"] for i in brief["items"]}


def test_seen_articles_are_not_repeated(stub, store, profile):
    items = [article(i) for i in range(6)]
    first = run(stub, store, profile, items, day=date(2026, 10, 31))
    second = run(stub, store, profile, items, day=AS_OF)
    assert not {i["url"] for i in first["items"]} & {i["url"] for i in second["items"]}


def test_replay_ignores_articles_from_the_future(stub, store, profile):
    items = [article(i, published="2026-10-30") for i in range(4)] + [article(9, published="2026-11-01")]
    brief = run(stub, store, profile, items, day=date(2026, 10, 31), is_replay=True)
    assert brief["is_replay"]
    assert "https://example.com/9" not in {i["url"] for i in brief["items"]}


def test_too_few_articles_is_reported_not_fatal(stub, store, profile):
    brief = run(stub, store, profile, [article(0)])
    assert len(brief["items"]) == 1
    assert any("Only 1 of 3" in w for w in brief["warnings"])


def test_one_source_may_repeat_to_reach_three_articles(stub, store, profile):
    items = [article(i, source="OnlySource") for i in range(4)] + [article(9, source="OtherSource")]
    brief = run(stub, store, profile, items)
    assert len(brief["items"]) == 3
    assert sorted(i["source"] for i in brief["items"]) == ["OnlySource", "OnlySource", "OtherSource"]


def test_a_single_source_can_never_fill_the_brief_alone(stub, store, profile):
    brief = run(stub, store, profile, [article(i, source="OnlySource") for i in range(5)])
    assert len(brief["items"]) == 2
    assert any("Only 2 of 3" in w for w in brief["warnings"])


def test_distinct_sources_are_preferred_when_available(stub, store, profile):
    items = [article(i, source="Big") for i in range(5)] + [article(7, source="B"), article(8, source="C")]
    brief = run(stub, store, profile, items)
    assert len({i["source"] for i in brief["items"]}) == 3


def test_replacement_is_found_when_only_one_new_source_is_left(stub, store, profile):
    # Two summaries fail twice, and only one unused source remains to replace them.
    stub.bad_quotes_for = 5
    items = [article(0, source="A"), article(1, source="B"), article(2, source="C"), article(3, source="D")]
    brief = run(stub, store, profile, items)
    assert brief["items"]
    assert len(brief["rejected"]) >= 1


def test_selector_adds_what_it_can_when_a_full_set_is_impossible():
    items = []
    for i in range(3):
        item = article(i, source="Same")
        item.update(final_score=0.5, topics=[])
        items.append(item)
    assert len(rank.choose_articles(items, [], set())) == 2


def test_rerunning_a_day_does_not_count_its_own_concepts_as_known(stub, store, profile):
    items = [article(i) for i in range(6)]
    run(stub, store, profile, items)
    stub.calls.clear()
    brief = run(stub, store, profile, items)
    assert len(brief["items"]) == 3
    assert brief["rejected"] == []
    assert len(store.concepts()) == 3  # the first run's concepts were replaced, not added to


def test_no_articles_produces_an_empty_brief(stub, store, profile):
    brief = run(stub, store, profile, [])
    assert brief["items"] == []
    assert any("No readable articles" in w for w in brief["warnings"])


def test_weights_change_ranking():
    db_post = article(1, topic="sql database query index postgres")
    dist_post = article(2, topic="raft consensus replication distributed")
    a = rank.prerank([db_post, dist_post], {"databases": 2.0, "distributed systems": 0.3}, AS_OF)
    b = rank.prerank([db_post, dist_post], {"databases": 0.3, "distributed systems": 2.0}, AS_OF)
    assert a[0]["url"] == db_post["url"]
    assert b[0]["url"] == dist_post["url"]


def test_session_length_prefers_the_target_window():
    items = []
    for i, words in enumerate([2000] * 4 + [1000] * 4):
        item = article(i)
        item["text"] = "word " * words
        item["final_score"] = 0.5
        item["topics"] = []
        items.append(item)
    chosen = rank.choose_articles(items, [], set())
    assert 15 <= rank.session_minutes(chosen) <= 20


def test_quote_matching_ignores_punctuation_and_case():
    assert quote_found("Leader-based Replication, works", "In short leader based replication works well")
    assert not quote_found("followers elect a king", "In short leader based replication works well")


def test_verification_fails_for_a_dead_link_or_known_concept():
    item = article(1)
    quote = " ".join(item["text"].split()[:8])
    summary = {"insights": [{"evidence_quote": quote}] * 3, "new_concept_name": "Raft"}
    assert passed(check_article(item, summary, AS_OF, [], lambda u: True))
    assert not passed(check_article(item, summary, AS_OF, [], lambda u: False))
    assert not passed(check_article(item, summary, AS_OF, ["raft"], lambda u: True))


def test_date_window():
    assert in_window("2026-10-30", AS_OF)
    assert not in_window("2026-11-02", AS_OF)
    assert not in_window("2026-10-01", AS_OF)
    assert not in_window("", AS_OF)
