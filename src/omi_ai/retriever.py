"""Fuzzy keyword retriever: narrows the catalog to a handful of candidate forms.

Jev's accuracy drops as unrelated material piles into a question, so the
command Choice only ever sees the top-k forms. Retrieval recall is therefore a
hard ceiling on the whole system.

Scoring: each query token is matched (typo-tolerant, via rapidfuzz) against the
tokens of each form's document; matches are weighted by IDF and summed.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from rapidfuzz import fuzz, process

from .catalog import Form, resolve_dynamic

STOP = {
    "a",
    "an",
    "the",
    "to",
    "my",
    "me",
    "i",
    "im",
    "i'm",
    "it",
    "its",
    "is",
    "be",
    "can",
    "could",
    "would",
    "you",
    "please",
    "pls",
    "make",
    "set",
    "get",
    "turn",
    "put",
    "do",
    "does",
    "of",
    "for",
    "on",
    "in",
    "at",
    "with",
    "and",
    "or",
    "this",
    "that",
    "so",
    "just",
    "some",
    "want",
    "wanna",
    "need",
    "like",
    "up",
}  # "up"/"on"/"off" stay out of the index, not the grammar

TOKEN = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    return [t for t in TOKEN.findall(text.lower()) if t not in STOP]


class Retriever:
    def __init__(
        self, forms: dict[str, Form], spec: dict, synonyms: dict[str, list[str]]
    ):
        self.forms = list(forms.values())
        self.synonyms = synonyms
        self.docs: list[set[str]] = []
        self.route_toks: list[set[str]] = []
        for f in self.forms:
            c = f.command
            s = spec.get("commands", {}).get(f.route, {})
            text = " ".join(
                [
                    f.route.replace("omarchy", ""),
                    c["summary"],
                    " ".join(c.get("aliases", [])),
                    s.get("description", ""),
                    " ".join(s.get("keywords", [])),
                    " ".join(v for a in f.args for v in a.values),
                    " ".join(
                        " ".join(resolve_dynamic(a.dynamic).values())
                        for a in f.args
                        if a.dynamic
                    ),
                ]
            )
            self.docs.append(set(tokens(text)))
            self.route_toks.append(set(tokens(f.route.replace("omarchy", ""))))
        df = Counter(t for d in self.docs for t in d)
        n = len(self.docs)
        self.idf = {t: math.log(1 + n / c) for t, c in df.items()}
        self.vocab = list(self.idf)

    def expand(self, q: str) -> list[str]:
        toks = tokens(q)
        out = list(toks)
        low = " " + " ".join(TOKEN.findall(q.lower())) + " "
        for phrase, extra in self.synonyms.items():
            if f" {phrase} " in low or phrase in toks:
                out += [t for e in extra for t in tokens(e)]
        return out

    def _match(self, tok: str) -> list[tuple[str, float]]:
        """Vocabulary tokens close to `tok`, with a similarity in [0, 1]."""
        if tok in self.idf:
            hits = [(tok, 1.0)]
        else:
            hits = []
        if len(tok) >= 4:
            for v, score, _ in process.extract(
                tok, self.vocab, scorer=fuzz.ratio, limit=3, score_cutoff=82
            ):
                if v != tok:
                    hits.append((v, score / 100 * 0.8))
            # prefix match: "screenshot" ~ "screen", "recording" ~ "screenrecording"
            for v in self.vocab:
                if (
                    len(v) >= 4
                    and v != tok
                    and (tok.startswith(v) or v.startswith(tok))
                ):
                    hits.append((v, 0.6))
        return hits

    def search(self, q: str, k: int = 8) -> list[tuple[Form, float]]:
        qt = self.expand(q)
        weights: dict[str, float] = {}
        for t in qt:
            for v, sim in self._match(t):
                weights[v] = max(weights.get(v, 0), sim * self.idf[v])
        scored = []
        for f, doc, rt in zip(self.forms, self.docs, self.route_toks):
            s = sum(w for v, w in weights.items() if v in doc)
            s += 0.5 * sum(
                w for v, w in weights.items() if v in rt
            )  # route words count extra
            s -= 0.01 * len(
                f.route.split()
            )  # tie-break toward shorter, more general routes
            scored.append((f, s))
        scored.sort(key=lambda x: -x[1])
        return scored[:k]
