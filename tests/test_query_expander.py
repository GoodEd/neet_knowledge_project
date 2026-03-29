import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rag.query_expander import expand_query


def test_short_query_gets_expanded():
    variants = expand_query("young modulus")

    assert len(variants) > 1


def test_long_query_not_expanded():
    query = "explain young modulus relation with stress and strain"

    assert expand_query(query) == [query]


def test_known_synonym_included():
    variants = " ".join(expand_query("young modulus")).lower()

    assert "elastic" in variants or "stress" in variants or "stiffness" in variants


def test_unknown_term_returns_original():
    assert expand_query("xyz123") == ["xyz123"]


def test_empty_query():
    assert expand_query("") == [""]


def test_wien_expansion():
    variants = " ".join(expand_query("wien law")).lower()

    assert "displacement" in variants or "blackbody" in variants
