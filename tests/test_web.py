from types import SimpleNamespace

from coworkers import web


def responses(monkeypatch, status_by_url):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(status_code=status_by_url[url])

    monkeypatch.setattr(web, "http_get", fake_get)
    return calls


def test_doi_links_are_checked_through_crossref(monkeypatch):
    # The publisher page would return 403 to a script even though the article exists.
    calls = responses(monkeypatch, {"https://api.crossref.org/works/10.1145/3847509": 200})
    assert web.url_ok("https://doi.org/10.1145/3847509")
    assert calls == ["https://api.crossref.org/works/10.1145/3847509"]


def test_unknown_doi_fails(monkeypatch):
    responses(monkeypatch, {"https://api.crossref.org/works/10.1145/0000": 404})
    assert not web.url_ok("https://doi.org/10.1145/0000")


def test_other_links_are_fetched_directly(monkeypatch):
    responses(monkeypatch, {"https://example.com/a": 403})
    assert not web.url_ok("https://example.com/a")
