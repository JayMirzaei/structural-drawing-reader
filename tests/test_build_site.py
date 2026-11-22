"""The static demo site builder (scripts/build_site.py) on a few questions about the example set."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "access_platform_set.pdf"


@pytest.fixture(scope="module")
def build_site():
    spec = importlib.util.spec_from_file_location("build_site", ROOT / "scripts" / "build_site.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while the class is created
    spec.loader.exec_module(module)
    yield module
    del sys.modules[spec.name]


@pytest.fixture(scope="module")
def site(build_site, tmp_path_factory):
    work = tmp_path_factory.mktemp("site")
    questions = work / "questions.yaml"
    questions.write_text(
        f"pdf: {EXAMPLE}\n"
        "questions:\n"
        "  - id: brace-size\n"
        "    q: What is the brace size?\n"
        "    expect: [L102X102X9.5]\n"
        "  - id: sheet-count\n"
        "    q: How many sheets are in the set?\n"
        "    expect: [5 sheet]\n"
        "  - id: overall-length\n"
        "    q: What is the overall length of the platform?\n"
        "    expect: ['10500']\n"
        "    known_limit: no rule finds it\n"
    )
    out = work / "site"
    sets = build_site.build(out, [questions], work / "cache")
    return out, sets


def test_the_site_has_a_landing_page_a_set_page_and_a_questions_page(site):
    out, sets = site
    assert [s.slug for s in sets] == ["access-platform-set"]
    for page in ("index.html", "style.css", "access-platform-set/index.html", "access-platform-set/questions.html"):
        assert (out / page).is_file(), page


def test_every_question_is_shown_with_its_status_and_cited_evidence(site):
    out, _ = site
    html = (out / "access-platform-set" / "questions.html").read_text()
    assert "What is the brace size?" in html and "L102X102X9.5" in html
    assert "known limit" in html and "no rule finds it" in html
    assert "2 of 2 scored questions pass" in html
    assert (out / "access-platform-set" / "evidence" / "brace-size_S-201.png").is_file()
    assert "S-201.label." in html  # the cited fact ids are listed


def test_every_local_link_and_image_resolves(site):
    out, _ = site
    for page in out.rglob("*.html"):
        for target in re.findall(r'(?:href|src)="([^"#]+)', page.read_text()):
            if not target.startswith("http"):
                assert (page.parent / target).resolve().is_file(), f"{page.name}: {target}"


def test_no_local_path_leaks_into_the_site(site):
    out, _ = site
    for page in out.rglob("*.html"):
        text = page.read_text()
        assert str(ROOT) not in text and str(out) not in text and str(Path.home()) not in text


def test_markdown_subset(build_site):
    assert build_site.markdown("**A** <b>\n- one\n- two\n\nend") == (
        "<p><strong>A</strong> &lt;b&gt;</p>\n<ul>\n<li>one</li>\n<li>two</li>\n</ul>\n<p>end</p>"
    )
