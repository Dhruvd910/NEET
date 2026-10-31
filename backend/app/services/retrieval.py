"""Document retrieval for grounded answers.

Ranking
- BM25 over document chunks and info articles (always on).
- When an embeddings provider is configured, chunks are also ranked by cosine similarity to the
  query, and the two rankings are merged with reciprocal-rank fusion. Semantic matching finds
  passages that use different words ("reservation" vs "quota"); BM25 keeps exact terms such as
  "EWS" or "Form 4" from being drowned out.
Retrieved text is evidence only: any instructions inside a document are never executed.
"""
import math
import re
from collections import Counter

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import DocumentChunk, InfoArticle, SourceDocument
from app.services.embeddings import cosine, embed, embeddings_enabled

STOP = {"the", "a", "an", "is", "are", "of", "to", "in", "for", "and", "or", "what", "how", "do", "i",
        "my", "me", "can", "does", "with", "on", "be", "it", "this", "that", "about", "which", "should"}
K1, B = 1.4, 0.75
RRF_K = 60
MAX_CANDIDATES = 3000


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9%]+", text.lower()) if t not in STOP and len(t) > 1]


def terms(query: str) -> list[str]:
    return list(dict.fromkeys(tokens(query)))[:12]


def bm25(query_terms: list[str], docs: list[list[str]]) -> list[float]:
    """BM25 score of each tokenised doc for the query terms (IDF computed over `docs`)."""
    n = len(docs)
    if not n or not query_terms:
        return [0.0] * n
    avgdl = sum(len(d) for d in docs) / n or 1.0
    df = Counter(t for d in docs for t in set(d) if t in query_terms)
    idf = {t: math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) for t in query_terms}
    scores = []
    for d in docs:
        tf = Counter(d)
        s = 0.0
        for t in query_terms:
            f = tf.get(t, 0)
            if f:
                s += idf[t] * f * (K1 + 1) / (f + K1 * (1 - B + B * len(d) / avgdl))
        scores.append(s)
    return scores


def _chunk_query(exam_year, authority, state, doc_type):
    q = select(DocumentChunk).join(SourceDocument)
    if exam_year:
        q = q.where(or_(SourceDocument.exam_year == exam_year, SourceDocument.exam_year.is_(None)))
    if authority:
        q = q.where(SourceDocument.authority == authority)
    if state:
        q = q.where(or_(SourceDocument.state == state, SourceDocument.state.is_(None)))
    if doc_type:
        q = q.where(SourceDocument.doc_type == doc_type)
    return q


def _chunk_result(ch: DocumentChunk, score: float) -> dict:
    d = ch.document
    return {"score": round(score, 4), "kind": "document", "title": d.title, "url": d.url,
            "authority": d.authority, "exam_year": d.exam_year, "page": ch.page, "section": ch.section,
            "extraction": ch.extraction,
            "publication_date": d.publication_date.isoformat() if d.publication_date else None,
            "verification_status": d.verification_status.value, "text": ch.text[:1500]}


def search_documents(db: Session, query: str, *, exam_year: int | None = None, authority: str | None = None,
                     state: str | None = None, doc_type: str | None = None, limit: int = 5) -> list[dict]:
    ts = terms(query)
    if not ts:
        return []
    base = _chunk_query(exam_year, authority, state, doc_type)

    # --- keyword (BM25) over chunks that contain at least one term
    kw_chunks = list(db.scalars(base.where(or_(*[DocumentChunk.text.ilike(f"%{t}%") for t in ts]))
                     .limit(MAX_CANDIDATES)))
    kw_scores = bm25(ts, [tokens(c.text) for c in kw_chunks])
    kw_rank = [c for _, c in sorted(zip(kw_scores, kw_chunks), key=lambda p: -p[0]) if _ > 0]

    # --- semantic over chunks with embeddings
    sem_rank: list[DocumentChunk] = []
    if embeddings_enabled():
        qv = embed([query], "query")
        if qv:
            vec_chunks = db.scalars(base.where(DocumentChunk.embedding.is_not(None)).limit(MAX_CANDIDATES)).all()
            sims = sorted(((cosine(qv[0], c.embedding), c) for c in vec_chunks), key=lambda p: -p[0])
            sem_rank = [c for s, c in sims[:50] if s > 0.3]

    fused: dict[int, float] = {}
    by_id: dict[int, DocumentChunk] = {}
    for ranking in (kw_rank[:50], sem_rank):
        for pos, c in enumerate(ranking):
            fused[c.id] = fused.get(c.id, 0.0) + 1.0 / (RRF_K + pos + 1)
            by_id[c.id] = c
    results = [_chunk_result(by_id[cid], s) for cid, s in fused.items()]

    # --- info articles (editorial summaries), BM25 with a title boost
    arts = db.scalars(select(InfoArticle).where(or_(*[InfoArticle.body.ilike(f"%{t}%") for t in ts],
                                                    *[InfoArticle.title.ilike(f"%{t}%") for t in ts])).limit(200)).all()
    art_scores = bm25(ts, [tokens(a.title) * 3 + tokens(a.body) for a in arts])
    ranked_arts = sorted(zip(art_scores, arts), key=lambda p: -p[0])
    for pos, (s, a) in enumerate(ranked_arts):
        if s <= 0:
            continue
        results.append({"score": round(1.0 / (RRF_K + pos + 1), 4), "kind": "info_article", "title": a.title,
                        "url": a.source_url, "authority": None, "exam_year": a.exam_year, "page": None,
                        "section": a.slug, "extraction": "text",
                        "publication_date": a.publication_date.isoformat() if a.publication_date else None,
                        "verification_status": a.verification_status.value, "text": a.body[:1500]})

    results.sort(key=lambda r: -r["score"])
    return results[:limit]
