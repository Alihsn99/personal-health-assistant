"""
Builds the local research corpus: pulls PubMed abstracts (NCBI E-utilities, no
API key required) for a curated set of topics relevant to the muscle-building
vs. longevity tradeoff, and embeds them into a local Chroma vector store for
retrieval by the assistant. Where a paper has free full text on PMC (PubMed
Central), that's pulled and chunked instead of just the abstract -- abstracts
alone tend to miss the methodology caveats and confounders that live in the
Discussion/Limitations sections, which matters for nutrition/longevity claims.

Run with: python src/ingest_research.py
"""

import time
import xml.etree.ElementTree as ET
from pathlib import Path

import chromadb
import requests

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
CORPUS_DIR = Path(__file__).resolve().parent.parent / "corpus"
CHROMA_DIR = CORPUS_DIR / "chroma_db"
RESULTS_PER_TOPIC = 15
REQUEST_DELAY_SEC = 0.4  # stay under NCBI's unauthenticated 3 req/sec limit
MAX_FULLTEXT_CHARS = 20_000  # cap per paper so a handful of long papers can't dominate the corpus
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 150

# Curated search topics covering the specific tension the assistant reasons about:
# protein/muscle-building signaling (mTOR, IGF-1, growth hormone) vs.
# caloric restriction / longevity pathways.
TOPICS = [
    "protein intake muscle protein synthesis aging",
    "caloric restriction longevity humans",
    "mTOR IGF-1 aging lifespan",
    "growth hormone IGF-1 cancer aging",
    "high protein diet mortality risk",
    "intermittent fasting longevity metabolic health",
    "resistance training longevity healthspan",
    "dietary protein restriction healthspan",
    "leucine mTOR muscle protein synthesis",
    "caloric restriction mimetics aging",
    "sarcopenia protein requirements older adults",
    "protein leverage hypothesis longevity",
]


def esearch(query: str, retmax: int) -> list[str]:
    resp = requests.get(
        f"{EUTILS}/esearch.fcgi",
        params={
            "db": "pubmed",
            "term": query,
            "retmax": retmax,
            "sort": "relevance",
            "retmode": "json",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["esearchresult"].get("idlist", [])


def efetch_abstracts(pmids: list[str]) -> list[dict]:
    if not pmids:
        return []
    resp = requests.get(
        f"{EUTILS}/efetch.fcgi",
        params={"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"},
        timeout=30,
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    records = []
    for article in root.findall(".//PubmedArticle"):
        pmid_el = article.find(".//PMID")
        title_el = article.find(".//ArticleTitle")
        year_el = article.find(".//PubDate/Year")
        journal_el = article.find(".//Journal/Title")
        abstract_parts = article.findall(".//AbstractText")

        if pmid_el is None or title_el is None or not abstract_parts:
            continue  # skip records without a usable abstract

        abstract_text = " ".join(
            (part.text or "") for part in abstract_parts
        ).strip()
        if not abstract_text:
            continue

        records.append(
            {
                "pmid": pmid_el.text,
                "title": (title_el.text or "").strip(),
                "year": year_el.text if year_el is not None else "unknown",
                "journal": journal_el.text if journal_el is not None else "unknown",
                "abstract": abstract_text,
            }
        )
    return records


def get_pmc_id(pmid: str) -> str | None:
    """Returns a PMC ID if this paper has a free full-text version there, else None."""
    resp = requests.get(
        f"{EUTILS}/elink.fcgi",
        params={"dbfrom": "pubmed", "db": "pmc", "id": pmid, "retmode": "json"},
        timeout=30,
    )
    resp.raise_for_status()
    for linkset in resp.json().get("linksets", []):
        for linksetdb in linkset.get("linksetdbs", []):
            if linksetdb.get("linkname") == "pubmed_pmc":
                links = linksetdb.get("links", [])
                if links:
                    return links[0]
    return None


def fetch_pmc_fulltext(pmcid: str) -> str | None:
    """Returns the concatenated body paragraphs of a PMC article, or None on failure."""
    try:
        resp = requests.get(
            f"{EUTILS}/efetch.fcgi",
            params={"db": "pmc", "id": pmcid, "rettype": "full", "retmode": "xml"},
            timeout=30,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        body = root.find(".//body")
        if body is None:
            return None
        paragraphs = ["".join(p.itertext()).strip() for p in body.iter("p")]
        text = "\n\n".join(p for p in paragraphs if p)
        return text[:MAX_FULLTEXT_CHARS] if len(text) > 500 else None
    except Exception:
        return None  # embargoed/malformed/etc -- caller falls back to the abstract


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + size])
        start += size - overlap
    return chunks


def main():
    CORPUS_DIR.mkdir(exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_or_create_collection(
        name="health_research",
        metadata={"description": "Curated PubMed abstracts/full text on protein/growth signaling vs. longevity"},
    )

    existing = collection.get(include=["metadatas"]) if collection.count() > 0 else {"metadatas": []}
    seen_pmids = {m["pmid"] for m in existing["metadatas"] if m.get("pmid")}
    total_added = 0

    for topic in TOPICS:
        print(f"[ingest] searching: {topic!r}")
        pmids = esearch(topic, RESULTS_PER_TOPIC)
        time.sleep(REQUEST_DELAY_SEC)

        new_pmids = [p for p in pmids if p not in seen_pmids]
        if not new_pmids:
            print("  -> no new results")
            continue

        records = efetch_abstracts(new_pmids)
        time.sleep(REQUEST_DELAY_SEC)

        if not records:
            print("  -> no usable abstracts")
            continue

        ids, documents, metadatas = [], [], []
        fulltext_count = 0

        for r in records:
            base_meta = {
                "pmid": r["pmid"],
                "title": r["title"],
                "year": r["year"],
                "journal": r["journal"],
                "topic": topic,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{r['pmid']}/",
            }

            pmcid = get_pmc_id(r["pmid"])
            time.sleep(REQUEST_DELAY_SEC)
            fulltext = fetch_pmc_fulltext(pmcid) if pmcid else None
            if fulltext:
                time.sleep(REQUEST_DELAY_SEC)

            if fulltext:
                for i, chunk in enumerate(chunk_text(fulltext)):
                    ids.append(f"{r['pmid']}_fc{i}")
                    documents.append(f"{r['title']}\n\n{chunk}")
                    metadatas.append({**base_meta, "source": "pmc_fulltext", "chunk_index": i})
                fulltext_count += 1
            else:
                ids.append(r["pmid"])
                documents.append(f"{r['title']}\n\n{r['abstract']}")
                metadatas.append({**base_meta, "source": "abstract"})

        collection.add(ids=ids, documents=documents, metadatas=metadatas)
        seen_pmids.update(r["pmid"] for r in records)
        total_added += len(records)
        print(f"  -> added {len(records)} papers ({fulltext_count} with full text, {len(records) - fulltext_count} abstract-only)")

    print(f"\n[ingest] done. corpus now has {collection.count()} chunks "
          f"({total_added} papers added this run). stored at {CHROMA_DIR}")


if __name__ == "__main__":
    main()
