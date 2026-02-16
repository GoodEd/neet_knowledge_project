#!/usr/bin/env python3
"""
NEET 2025 Paper Discussion - Batch YouTube Ingestion Script
Finds and ingests NEET 2025 paper discussion videos with transcripts.
Handles failures gracefully and reports results.
"""

import sys
import os
import json
import time
import traceback

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.processors.youtube_processor import YouTubeProcessor
from src.rag.vector_store import VectorStoreManager as VectorStore

# =============================================================================
# VIDEO DATABASE: All NEET 2025 paper discussion videos discovered via web search
# =============================================================================
NEET_2025_VIDEOS = [
    # ALLEN NEET - Live Paper Solution (6+ hours, covers all subjects)
    {
        "id": "Epk7DjFybDk",
        "title": "ALLEN NEET 2025 Live Paper Solution & Answer Key",
        "channel": "ALLEN NEET",
    },
    # PW Vidyapeeth - Live Paper Solution & Analysis
    {
        "id": "_GZGYRdQo1M",
        "title": "PW Vidyapeeth NEET 2025 Live Paper Solution & Analysis",
        "channel": "PW Vidyapeeth",
    },
    # Infinity Learn NEET - Answer Key & Paper Discussion
    {
        "id": "Du1lfG0PF-Y",
        "title": "NEET Answer Key 2025 Paper Discussion & Expected Cutoff",
        "channel": "Infinity Learn NEET",
    },
    # Various NEET 2025 specific discussions
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
    # Physics specific
    {
        "id": "wM879wgdXkc",
        "title": "NEET 2025 Physics Paper Discussion - Full Syllabus Test",
        "channel": "NEW LIGHT NEET",
    },
    {
        "id": "kcJ2FaOuZbo",
        "title": "NEET 2025 Physics Paper Analysis",
        "channel": "Unknown",
    },
    {"id": "-j9zURwuC2s", "title": "NEET 2025 Physics Solutions", "channel": "Unknown"},
    # Biology specific
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
    # Chemistry specific
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
    # Additional from search
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
    # Original search results
    {
        "id": "nXPX15FPfsE",
        "title": "NEET 2025 Paper Discussion Search Result",
        "channel": "Unknown",
    },
    {
        "id": "STUAIWx_m7Q",
        "title": "NEET 2024/2025 Paper Discussion Search Result",
        "channel": "Unknown",
    },
]


def batch_ingest():
    """Attempt to ingest all NEET 2025 videos, tracking successes and failures."""

    processor = YouTubeProcessor()
    vector_store = VectorStore()

    results = {
        "success": [],
        "no_transcript": [],
        "unavailable": [],
        "other_error": [],
    }

    total = len(NEET_2025_VIDEOS)

    for i, video in enumerate(NEET_2025_VIDEOS, 1):
        video_id = video["id"]
        title = video["title"]
        url = f"https://www.youtube.com/watch?v={video_id}"

        print(f"\n[{i}/{total}] Processing: {title}")
        print(f"  URL: {url}")

        try:
            result = processor.process(url)
            chunks = result.get("documents", []) if isinstance(result, dict) else result

            if chunks:
                for chunk in chunks:
                    chunk.metadata["title"] = title
                    chunk.metadata["channel"] = video.get("channel", "Unknown")
                    chunk.metadata["source_type"] = "youtube"
                    chunk.metadata["exam"] = "NEET 2025"
                    chunk.metadata["url"] = url

                vector_store.add_documents(chunks)

                results["success"].append(
                    {"id": video_id, "title": title, "chunks": len(chunks)}
                )
                print(f"  SUCCESS: {len(chunks)} chunks ingested")
            else:
                results["no_transcript"].append({"id": video_id, "title": title})
                print(f"  SKIP: No chunks returned")

        except RuntimeError as e:
            err_msg = str(e)
            if "No transcript" in err_msg:
                results["no_transcript"].append(
                    {"id": video_id, "title": title, "error": err_msg[:100]}
                )
                print(f"  SKIP: No transcript available")
            elif "no longer available" in err_msg or "VideoUnavailable" in err_msg:
                results["unavailable"].append({"id": video_id, "title": title})
                print(f"  SKIP: Video unavailable")
            else:
                results["other_error"].append(
                    {"id": video_id, "title": title, "error": err_msg[:200]}
                )
                print(f"  ERROR: {err_msg[:100]}")
        except Exception as e:
            results["other_error"].append(
                {"id": video_id, "title": title, "error": str(e)[:200]}
            )
            print(f"  ERROR: {str(e)[:100]}")

        # Small delay to be polite to YouTube
        time.sleep(1)

    # Print summary
    print("\n" + "=" * 60)
    print("BATCH INGESTION SUMMARY")
    print("=" * 60)
    print(f"Total videos attempted: {total}")
    print(f"Successfully ingested:  {len(results['success'])}")
    print(f"No transcript:          {len(results['no_transcript'])}")
    print(f"Video unavailable:      {len(results['unavailable'])}")
    print(f"Other errors:           {len(results['other_error'])}")

    total_chunks = sum(v["chunks"] for v in results["success"])
    print(f"\nTotal chunks in vector store: {total_chunks}")

    if results["success"]:
        print("\nSuccessfully ingested videos:")
        for v in results["success"]:
            print(f"  - {v['title']} ({v['chunks']} chunks)")

    # Save results to file
    with open("data/ingestion_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nDetailed results saved to data/ingestion_results.json")

    return results


if __name__ == "__main__":
    batch_ingest()
