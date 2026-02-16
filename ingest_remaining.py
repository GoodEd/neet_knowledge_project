#!/usr/bin/env python3
"""Ingest the 11 remaining YouTube videos that weren't captured in the first batch."""

import sys, os, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from youtube_transcript_api import YouTubeTranscriptApi
from langchain_core.documents import Document
from src.rag.vector_store import VectorStoreManager

REMAINING_VIDEOS = [
    {
        "id": "1h-hnzS7cpA",
        "title": "NEET 2025 Biology Paper Discussion",
        "channel": "Unknown",
    },
    {
        "id": "-uvzr4YeSZU",
        "title": "NEET 2025 Chemistry Solutions",
        "channel": "Unknown",
    },
    {
        "id": "QjrIDTN2FIU",
        "title": "NEET 2025 Chemistry Paper Discussion May 13",
        "channel": "Unknown",
    },
    {
        "id": "dbff4M499Mk",
        "title": "NEET 2025 Paper Discussion May 14 Full",
        "channel": "Unknown",
    },
    {
        "id": "PaYVVIt29g0",
        "title": "NEET 2025 Paper Solution Oct",
        "channel": "Unknown",
    },
    {
        "id": "L_inytDTlkM",
        "title": "NEET 2025 Paper Discussion Oct",
        "channel": "Unknown",
    },
    {
        "id": "kuyXcjwjLmc",
        "title": "NEET 2025 Paper Discussion Oct 23",
        "channel": "Unknown",
    },
    {
        "id": "9xtvLebHcHs",
        "title": "NEET 2025 Paper Discussion Apr 25",
        "channel": "Unknown",
    },
    {
        "id": "5jKeq12h7_8",
        "title": "NEET 2025 Paper Discussion Apr 29",
        "channel": "Unknown",
    },
    {
        "id": "nXPX15FPfsE",
        "title": "NEET 2025 Paper Discussion Search Result",
        "channel": "Unknown",
    },
    {
        "id": "STUAIWx_m7Q",
        "title": "NEET 2024/2025 Paper Discussion",
        "channel": "Unknown",
    },
]

CHUNK_SIZE = 1000


def transcript_to_documents(snippets, video_id, title, channel):
    url = f"https://www.youtube.com/watch?v={video_id}"
    documents = []
    current_texts = []
    current_start = snippets[0].start if snippets else 0
    current_chars = 0

    for snippet in snippets:
        current_texts.append(snippet.text)
        current_chars += len(snippet.text)
        if current_chars >= CHUNK_SIZE:
            doc = Document(
                page_content=" ".join(current_texts),
                metadata={
                    "source": url,
                    "video_id": video_id,
                    "title": title,
                    "channel": channel,
                    "start_time": current_start,
                    "source_type": "youtube",
                    "exam": "NEET 2025",
                    "url": url,
                },
            )
            documents.append(doc)
            current_texts = []
            current_start = snippet.start
            current_chars = 0

    if current_texts:
        doc = Document(
            page_content=" ".join(current_texts),
            metadata={
                "source": url,
                "video_id": video_id,
                "title": title,
                "channel": channel,
                "start_time": current_start,
                "source_type": "youtube",
                "exam": "NEET 2025",
                "url": url,
            },
        )
        documents.append(doc)
    return documents


def main():
    print("=== Ingesting remaining 11 videos ===", flush=True)
    api = YouTubeTranscriptApi()
    vs = VectorStoreManager()
    vs.load_vectorstore()
    print(f"Loaded FAISS index: {vs.vectorstore.index.ntotal} docs", flush=True)

    results = {"success": [], "failed": []}

    for i, video in enumerate(REMAINING_VIDEOS, 1):
        vid = video["id"]
        title = video["title"]
        print(f"\n[{i}/11] {title} ({vid})", flush=True)

        try:
            transcript_list = api.list(vid)
            available_langs = [t.language_code for t in transcript_list]
            print(f"  Languages: {available_langs}", flush=True)

            snippets = None
            for lang in ["en", "hi", "en-IN", "hi-IN"]:
                if lang in available_langs:
                    snippets = api.fetch(vid, languages=[lang])
                    print(f"  Fetched in: {lang}", flush=True)
                    break

            if snippets is None:
                for t in transcript_list:
                    if t.is_translatable:
                        snippets = t.translate("en").fetch()
                        print(f"  Translated from {t.language_code}", flush=True)
                        break

            if snippets is None and available_langs:
                snippets = api.fetch(vid, languages=[available_langs[0]])
                print(f"  Fallback language: {available_langs[0]}", flush=True)

            if snippets:
                docs = transcript_to_documents(snippets, vid, title, video["channel"])
                vs.add_documents(docs)
                results["success"].append(
                    {"id": vid, "title": title, "chunks": len(docs)}
                )
                print(f"  SUCCESS: {len(docs)} chunks", flush=True)
            else:
                results["failed"].append(
                    {"id": vid, "title": title, "reason": "no transcript"}
                )
                print(f"  SKIP: No transcript", flush=True)

        except Exception as e:
            results["failed"].append(
                {"id": vid, "title": title, "reason": str(e)[:100]}
            )
            print(f"  FAIL: {str(e)[:80]}", flush=True)

        time.sleep(5)  # longer delay to avoid rate limiting

    print(f"\n{'=' * 60}", flush=True)
    print(
        f"Success: {len(results['success'])}, Failed: {len(results['failed'])}",
        flush=True,
    )
    print(f"Final FAISS size: {vs.vectorstore.index.ntotal}", flush=True)

    with open("data/ingestion_remaining_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Results saved to data/ingestion_remaining_results.json", flush=True)


if __name__ == "__main__":
    main()
