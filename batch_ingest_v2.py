#!/usr/bin/env python3
"""
Batch YouTube transcript ingestion using youtube_transcript_api directly.
Bypasses yt-dlp (which is 429-rate-limited) and uses timedtext API endpoint.
"""

import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from youtube_transcript_api import YouTubeTranscriptApi
from langchain_core.documents import Document
from src.rag.vector_store import VectorStoreManager

NEET_2025_VIDEOS = [
    {
        "id": "Epk7DjFybDk",
        "title": "ALLEN NEET 2025 Live Paper Solution",
        "channel": "ALLEN NEET",
    },
    {
        "id": "_GZGYRdQo1M",
        "title": "PW Vidyapeeth NEET 2025 Live Paper Solution",
        "channel": "PW Vidyapeeth",
    },
    {
        "id": "Du1lfG0PF-Y",
        "title": "NEET Answer Key 2025 Paper Discussion",
        "channel": "Infinity Learn NEET",
    },
    {"id": "Z85qB7B6rug", "title": "NEET 2025 Paper Discussion", "channel": "Unknown"},
    {
        "id": "bLDNvb69Ldo",
        "title": "NEET 2025 Paper Analysis May 2025",
        "channel": "Unknown",
    },
    {
        "id": "K1ljursjYSs",
        "title": "NEET 2025 Paper Solution June",
        "channel": "Unknown",
    },
    {
        "id": "mea4MWYfYv8",
        "title": "NEET 2025 Paper Discussion May 14",
        "channel": "Unknown",
    },
    {
        "id": "IE4cUisVJww",
        "title": "NEET 2025 Paper Discussion Desktop",
        "channel": "Unknown",
    },
    {
        "id": "h3bQTWTc87s",
        "title": "NEET 2025 Answer Key Discussion",
        "channel": "Unknown",
    },
    {"id": "7w_YbQK1XF0", "title": "NEET 2025 Answer Key Video", "channel": "Unknown"},
    {
        "id": "wM879wgdXkc",
        "title": "NEET 2025 Physics Paper Discussion",
        "channel": "NEW LIGHT NEET",
    },
    {
        "id": "kcJ2FaOuZbo",
        "title": "NEET 2025 Physics Paper Analysis",
        "channel": "Unknown",
    },
    {"id": "-j9zURwuC2s", "title": "NEET 2025 Physics Solutions", "channel": "Unknown"},
    {
        "id": "1h-hnzS7cpA",
        "title": "NEET 2025 Biology Paper Discussion",
        "channel": "Unknown",
    },
    {
        "id": "Q_Y9foIBvgg",
        "title": "NEET 2025 Biology Paper Analysis May 14",
        "channel": "Unknown",
    },
    {
        "id": "_YWf9p4_PmU",
        "title": "NEET 2025 Chemistry Paper Discussion",
        "channel": "Unknown",
    },
    {
        "id": "DjxRDbYm_eA",
        "title": "NEET 2025 Chemistry Paper Analysis",
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
    api = YouTubeTranscriptApi()
    vs = VectorStoreManager()

    try:
        vs.load_vectorstore()
        print("Loaded existing FAISS index")
    except FileNotFoundError:
        print("No existing index, will create new one")

    results = {"success": [], "no_transcript": [], "unavailable": [], "error": []}
    total = len(NEET_2025_VIDEOS)

    for i, video in enumerate(NEET_2025_VIDEOS, 1):
        vid = video["id"]
        title = video["title"]
        channel = video["channel"]

        print(f"\n[{i}/{total}] {title} ({vid})")

        try:
            transcript_list = api.list(vid)
            available_langs = [t.language_code for t in transcript_list]
            print(f"  Languages available: {available_langs}")

            snippets = None
            for lang in ["en", "hi", "en-IN", "hi-IN"]:
                if lang in available_langs:
                    snippets = api.fetch(vid, languages=[lang])
                    print(f"  Fetched transcript in: {lang}")
                    break

            if snippets is None:
                for t in transcript_list:
                    if t.is_translatable:
                        snippets = t.translate("en").fetch()
                        print(f"  Translated from {t.language_code} to en")
                        break

            if snippets is None and available_langs:
                snippets = api.fetch(vid, languages=[available_langs[0]])
                print(f"  Fetched in fallback language: {available_langs[0]}")

            if snippets:
                docs = transcript_to_documents(snippets, vid, title, channel)
                vs.add_documents(docs)
                results["success"].append(
                    {"id": vid, "title": title, "chunks": len(docs)}
                )
                print(
                    f"  SUCCESS: {len(docs)} chunks ingested ({len(snippets)} snippets)"
                )
            else:
                results["no_transcript"].append({"id": vid, "title": title})
                print(f"  SKIP: No transcript found")

        except Exception as e:
            err = str(e)
            if "No transcript" in err or "TranscriptsDisabled" in err:
                results["no_transcript"].append(
                    {"id": vid, "title": title, "error": err[:100]}
                )
                print(f"  SKIP: {err[:80]}")
            elif "VideoUnavailable" in err:
                results["unavailable"].append({"id": vid, "title": title})
                print(f"  SKIP: Video unavailable")
            else:
                results["error"].append({"id": vid, "title": title, "error": err[:200]})
                print(f"  ERROR: {err[:100]}")

        time.sleep(3)

    print("\n" + "=" * 60)
    print("BATCH INGESTION SUMMARY")
    print("=" * 60)
    print(f"Total attempted: {total}")
    print(f"Success:         {len(results['success'])}")
    print(f"No transcript:   {len(results['no_transcript'])}")
    print(f"Unavailable:     {len(results['unavailable'])}")
    print(f"Errors:          {len(results['error'])}")

    total_chunks = sum(v["chunks"] for v in results["success"])
    print(f"\nTotal video chunks added: {total_chunks}")

    if results["success"]:
        print("\nSuccessfully ingested:")
        for v in results["success"]:
            print(f"  - {v['title']} ({v['chunks']} chunks)")

    with open("data/ingestion_results_v2.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to data/ingestion_results_v2.json")


if __name__ == "__main__":
    main()
