#!/usr/bin/env python3
"""
NEET 2025 Question-to-Video Locator
Maps all 180 NEET 2025 questions to YouTube video segments where they are discussed.
Uses the FAISS vector store with embedded question text and YouTube transcripts.
"""

import re
import sys
import os
import json
import csv
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.rag.vector_store import VectorStoreManager

# ------- Question extraction (same logic as reingest_neet_pdf.py) -------

SUBJECT_RANGES = [
    (1, 45, "PHYSICS"),
    (46, 90, "CHEMISTRY"),
    (91, 180, "BIOLOGY"),
]


def get_subject(q_num: int) -> str:
    for start, end, subject in SUBJECT_RANGES:
        if start <= q_num <= end:
            return subject
    return "UNKNOWN"


def extract_questions(text: str) -> list[dict]:
    header_pattern = (
        r"VETRII NEET GATEWAY\s*\n.*?NEET UG.*?\n.*?\d{10}\|\d{10}\|\d{10}\s*\n?"
    )
    text = re.sub(header_pattern, "\n", text)
    text = re.sub(r"\n\s*PHYSICS\s*\n", "\n", text)
    text = re.sub(r"\n\s*CHEMISTRY\s*\n", "\n", text)
    text = re.sub(r"\n\s*BIOLOGY\s*\n", "\n", text)

    q_positions = []
    for m in re.finditer(r"(?:^|\n)\s*(\d{1,3})\.\s", text):
        q_num = int(m.group(1))
        if 1 <= q_num <= 180:
            q_positions.append((q_num, m.start()))

    seen = set()
    unique_positions = []
    for q_num, pos in q_positions:
        if q_num not in seen:
            seen.add(q_num)
            unique_positions.append((q_num, pos))

    unique_positions.sort(key=lambda x: x[1])

    questions = []
    for idx, (q_num, start_pos) in enumerate(unique_positions):
        if idx + 1 < len(unique_positions):
            end_pos = unique_positions[idx + 1][1]
        else:
            end_pos = len(text)

        q_text = text[start_pos:end_pos].strip()
        q_text = re.sub(r"^\d{1,3}\.\s*", "", q_text).strip()

        if q_text:
            questions.append(
                {
                    "number": q_num,
                    "text": q_text,
                    "subject": get_subject(q_num),
                }
            )

    return questions


def format_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS format."""
    td = timedelta(seconds=int(seconds))
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def youtube_url_at_time(video_id: str, seconds: float) -> str:
    """Generate a YouTube URL with timestamp."""
    return f"https://www.youtube.com/watch?v={video_id}&t={int(seconds)}s"


def run_locator():
    print("=" * 70, flush=True)
    print("NEET 2025 QUESTION-TO-VIDEO LOCATOR", flush=True)
    print("=" * 70, flush=True)

    # 1. Load questions
    text_path = "data/neet_2025_paper_text.txt"
    if not os.path.exists(text_path):
        print(f"ERROR: {text_path} not found")
        sys.exit(1)

    with open(text_path, "r") as f:
        raw_text = f.read()

    questions = extract_questions(raw_text)
    print(f"\nExtracted {len(questions)} questions from PDF text", flush=True)

    # 2. Load vector store
    print("Loading FAISS vector store...", flush=True)
    vs = VectorStoreManager()
    vs.load_vectorstore()
    total_docs = vs.vectorstore.index.ntotal
    print(f"Vector store loaded: {total_docs} documents", flush=True)

    # 3. Query each question against YouTube transcripts
    # IMPORTANT: Don't use FAISS filter= param — it only post-filters from initial k results,
    # so if top-k are PDF docs, you get 0 YouTube results. Instead, fetch more results
    # without filter, then manually keep only YouTube source_type docs.
    FETCH_K = 30  # Fetch extra candidates to ensure YouTube docs are found
    MAX_YOUTUBE = 5  # Keep top 5 YouTube matches per question
    SCORE_THRESHOLD = 1.5  # FAISS L2 distance — lower is better

    results = []
    covered = 0
    uncovered = 0

    print(
        f"\nSearching for video coverage of each question (fetch {FETCH_K}, keep top {MAX_YOUTUBE} YouTube, threshold < {SCORE_THRESHOLD})...\n",
        flush=True,
    )

    for q in questions:
        q_num = q["number"]
        subject = q["subject"]
        # Use first 500 chars of question text as query
        query_text = q["text"][:500]

        try:
            all_matches = vs.similarity_search_with_score(
                query=query_text,
                k=FETCH_K,
            )
        except Exception as e:
            print(f"  Q{q_num}: ERROR - {e}", flush=True)
            results.append(
                {
                    "question_number": q_num,
                    "subject": subject,
                    "question_preview": query_text[:80],
                    "video_matches": [],
                    "covered": False,
                }
            )
            uncovered += 1
            continue

        # Post-filter: only keep YouTube docs
        matches = [
            (doc, score)
            for doc, score in all_matches
            if doc.metadata.get("source_type") == "youtube"
        ][:MAX_YOUTUBE]

        video_matches = []
        for doc, score in matches:
            score_f = float(score)  # Convert numpy float32 to Python float
            if score_f < SCORE_THRESHOLD:
                meta = doc.metadata
                video_matches.append(
                    {
                        "video_id": meta.get("video_id", ""),
                        "title": meta.get("title", ""),
                        "channel": meta.get("channel", ""),
                        "start_time_seconds": float(meta.get("start_time", 0)),
                        "start_time_formatted": format_timestamp(
                            meta.get("start_time", 0)
                        ),
                        "url": youtube_url_at_time(
                            meta.get("video_id", ""), meta.get("start_time", 0)
                        ),
                        "score": round(score_f, 4),
                        "snippet": doc.page_content[:150],
                    }
                )

        is_covered = len(video_matches) > 0
        if is_covered:
            covered += 1
            best = video_matches[0]
            print(
                f"  Q{q_num:3d} [{subject:9s}] ✓ {len(video_matches)} match(es) | Best: {best['title'][:40]} @ {best['start_time_formatted']} (score={best['score']:.3f})",
                flush=True,
            )
        else:
            uncovered += 1
            if matches:
                best_score = float(matches[0][1])
                print(
                    f"  Q{q_num:3d} [{subject:9s}] ✗ No match below threshold (best score={best_score:.3f})",
                    flush=True,
                )
            else:
                print(
                    f"  Q{q_num:3d} [{subject:9s}] ✗ No YouTube results in top {FETCH_K}",
                    flush=True,
                )

        best_score_val = None
        if video_matches:
            best_score_val = video_matches[0]["score"]
        elif matches:
            best_score_val = round(float(matches[0][1]), 4)

        results.append(
            {
                "question_number": q_num,
                "subject": subject,
                "question_preview": query_text[:120],
                "video_matches": video_matches,
                "covered": is_covered,
                "best_score": best_score_val,
            }
        )

    # 4. Generate coverage report
    print(f"\n{'=' * 70}", flush=True)
    print("COVERAGE REPORT", flush=True)
    print(f"{'=' * 70}", flush=True)
    print(f"Total questions:    {len(questions)}", flush=True)
    print(
        f"Covered:            {covered} ({covered * 100 / len(questions):.1f}%)",
        flush=True,
    )
    print(
        f"Uncovered:          {uncovered} ({uncovered * 100 / len(questions):.1f}%)",
        flush=True,
    )

    # Per-subject breakdown
    for subject in ["PHYSICS", "CHEMISTRY", "BIOLOGY"]:
        subj_results = [r for r in results if r["subject"] == subject]
        subj_covered = sum(1 for r in subj_results if r["covered"])
        total = len(subj_results)
        print(
            f"  {subject:10s}: {subj_covered}/{total} covered ({subj_covered * 100 / total:.0f}%)"
            if total > 0
            else f"  {subject}: 0",
            flush=True,
        )

    # Video contribution stats
    video_contrib = {}
    for r in results:
        for vm in r["video_matches"]:
            vid = vm["video_id"]
            if vid not in video_contrib:
                video_contrib[vid] = {
                    "title": vm["title"],
                    "channel": vm["channel"],
                    "questions": set(),
                }
            video_contrib[vid]["questions"].add(r["question_number"])

    print(f"\n{'=' * 70}", flush=True)
    print("VIDEO CONTRIBUTION (questions covered per video)", flush=True)
    print(f"{'=' * 70}", flush=True)
    for vid, info in sorted(
        video_contrib.items(), key=lambda x: -len(x[1]["questions"])
    ):
        q_list = sorted(info["questions"])
        print(
            f"  {info['title'][:50]:50s} | {len(q_list):3d} questions | {info['channel']}",
            flush=True,
        )

    # 5. Save results
    # JSON (full results)
    json_path = "data/neet_2025_coverage_report.json"
    with open(json_path, "w") as f:
        # Convert sets to lists for JSON serialization
        json_results = []
        for r in results:
            json_results.append(r)
        json.dump(
            {
                "summary": {
                    "total_questions": len(questions),
                    "covered": covered,
                    "uncovered": uncovered,
                    "coverage_pct": round(covered * 100 / len(questions), 1),
                    "score_threshold": SCORE_THRESHOLD,
                    "top_k": MAX_YOUTUBE,
                },
                "questions": json_results,
                "video_contributions": {
                    vid: {
                        "title": info["title"],
                        "channel": info["channel"],
                        "question_count": len(info["questions"]),
                        "questions": sorted(info["questions"]),
                    }
                    for vid, info in video_contrib.items()
                },
            },
            f,
            indent=2,
        )
    print(f"\nFull results saved to: {json_path}", flush=True)

    # CSV (one row per question-video match, easy to view)
    csv_path = "data/neet_2025_coverage_report.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "Question#",
                "Subject",
                "Question Preview",
                "Video Title",
                "Video ID",
                "Timestamp",
                "URL",
                "Score",
            ]
        )
        for r in results:
            if r["video_matches"]:
                for vm in r["video_matches"]:
                    writer.writerow(
                        [
                            r["question_number"],
                            r["subject"],
                            r["question_preview"][:80],
                            vm["title"],
                            vm["video_id"],
                            vm["start_time_formatted"],
                            vm["url"],
                            vm["score"],
                        ]
                    )
            else:
                writer.writerow(
                    [
                        r["question_number"],
                        r["subject"],
                        r["question_preview"][:80],
                        "NO MATCH",
                        "",
                        "",
                        "",
                        "",
                    ]
                )
    print(f"CSV report saved to:  {csv_path}", flush=True)

    # Uncovered questions list
    uncovered_qs = [r for r in results if not r["covered"]]
    if uncovered_qs:
        print(f"\nUncovered questions ({len(uncovered_qs)}):", flush=True)
        for r in uncovered_qs:
            print(
                f"  Q{r['question_number']:3d} [{r['subject']:9s}] {r['question_preview'][:60]}...",
                flush=True,
            )

    print(f"\n{'=' * 70}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    run_locator()
