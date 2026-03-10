import logging
import os
import re
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import boto3
import pandas as pd
import requests

try:
    from markdownify import markdownify as md
except ImportError:
    md = None

logger = logging.getLogger(__name__)


class CSVProcessor:
    def __init__(
        self,
        id_col_hints: Optional[List[str]] = None,
        question_col_hints: Optional[List[str]] = None,
        explanation_col_hints: Optional[List[str]] = None,
        chapter_col_hints: Optional[List[str]] = None,
        topic_col_hints: Optional[List[str]] = None,
    ):
        self.id_col_hints = id_col_hints or [
            "id",
            "question_id",
            "qid",
            "external_id",
        ]
        self.question_col_hints = question_col_hints or [
            "question",
            "q",
            "query",
            "problem",
        ]
        self.explanation_col_hints = explanation_col_hints or [
            "explanation",
            "solution",
            "answer",
            "ans",
        ]
        self.chapter_col_hints = chapter_col_hints or [
            "chapter_name",
            "chapter",
            "subject_chapter",
        ]
        self.topic_col_hints = topic_col_hints or [
            "topic_names",
            "topic_name",
            "topic",
            "topics",
        ]

    def _find_column(self, columns: List[str], hints: List[str]) -> Optional[str]:
        cols_lower = {c.lower(): c for c in columns}

        for hint in hints:
            if hint in cols_lower:
                return cols_lower[hint]

        for col in columns:
            col_lower = col.lower()
            for hint in hints:
                if hint in col_lower:
                    return col

        return None

    def _html_to_markdown(self, value: Any) -> str:
        if value is None or pd.isna(value):
            return ""

        text = str(value)
        if not text.strip():
            return ""

        if md is None:
            try:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(text, "html.parser")
                return soup.get_text(separator=" ", strip=True)
            except Exception:
                return text.strip()

        markdown_text = md(text, heading_style="ATX")
        markdown_text = re.sub(r"\n{3,}", "\n\n", markdown_text)
        return markdown_text.strip()

    def _download_to_local_if_needed(self, file_path: str) -> tuple[str, Optional[str]]:
        is_s3 = file_path.startswith("s3://")
        is_http = file_path.startswith("http://") or file_path.startswith("https://")

        if not is_s3 and not is_http:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"CSV file not found: {file_path}")
            return file_path, None

        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        local_path = tmp_file.name
        tmp_file.close()

        if is_s3:
            parsed = urlparse(file_path)
            bucket = parsed.netloc
            key = parsed.path.lstrip("/")
            s3 = boto3.client("s3")
            s3.download_file(bucket, key, local_path)
        else:
            response = requests.get(file_path, timeout=60)
            response.raise_for_status()
            with open(local_path, "wb") as f:
                f.write(response.content)

        return local_path, local_path

    def process(self, file_path: str) -> Dict[str, Any]:
        temp_path: Optional[str] = None
        try:
            process_path, temp_path = self._download_to_local_if_needed(file_path)

            try:
                df = pd.read_csv(process_path, encoding="utf-8")
            except UnicodeDecodeError:
                df = pd.read_csv(process_path, encoding="latin1")

            columns = list(df.columns)
            id_col = self._find_column(columns, self.id_col_hints)
            q_col = self._find_column(columns, self.question_col_hints)
            e_col = self._find_column(columns, self.explanation_col_hints)
            chapter_col = self._find_column(columns, self.chapter_col_hints)
            topic_col = self._find_column(columns, self.topic_col_hints)

            if not q_col:
                raise ValueError(
                    f"Could not find a question column in {file_path}. Available: {columns}"
                )
            if not e_col:
                raise ValueError(
                    f"Could not find an explanation/solution column in {file_path}. Available: {columns}"
                )

            source_name = os.path.basename(file_path)
            now = datetime.now().isoformat()
            documents: List[Dict[str, Any]] = []

            for idx, row in df.iterrows():
                question_md = self._html_to_markdown(row[q_col])
                explanation_md = self._html_to_markdown(row[e_col])

                if not question_md and not explanation_md:
                    continue

                question_id = None
                if id_col:
                    raw_id = row[id_col]
                    if raw_id is not None and not pd.isna(raw_id):
                        question_id = str(raw_id).strip()

                if not question_id:
                    question_id = str(idx)

                chapter_name = ""
                if chapter_col:
                    raw = row[chapter_col]
                    if raw is not None and not pd.isna(raw):
                        chapter_name = str(raw).strip()

                topic_names = ""
                if topic_col:
                    raw = row[topic_col]
                    if raw is not None and not pd.isna(raw):
                        topic_names = str(raw).strip()

                prefix_parts = []
                if chapter_name:
                    prefix_parts.append(f"Chapter: {chapter_name}")
                if topic_names:
                    prefix_parts.append(f"Topic: {topic_names}")
                prefix = "\n".join(prefix_parts)

                qa_body = (
                    f"Question:\n{question_md}\n\n"
                    f"Official Solution/Explanation:\n{explanation_md}"
                )
                combined_content = f"{prefix}\n\n{qa_body}" if prefix else qa_body

                doc_meta = {
                    "content": combined_content,
                    "source": source_name,
                    "source_type": "csv",
                    "content_type": "csv_qa_pair",
                    "row_index": idx,
                    "question_id": question_id,
                    "timestamp": now,
                }
                if chapter_name:
                    doc_meta["chapter_name"] = chapter_name
                if topic_names:
                    doc_meta["topic_names"] = topic_names

                documents.append(doc_meta)

            return {
                "documents": documents,
                "source": source_name,
                "total_rows_processed": len(documents),
                "processed_at": now,
            }
        except Exception as e:
            logger.exception("Failed to process CSV")
            raise RuntimeError(f"Error processing CSV {file_path}: {str(e)}")
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
