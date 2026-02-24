import os
import re
import pandas as pd
from typing import Dict, Any, List
from datetime import datetime
import logging

try:
    from markdownify import markdownify as md
except ImportError:
    md = None

logger = logging.getLogger(__name__)

class CSVProcessor:
    """
    Processor for structured Q&A CSV files (typically HTML columns).
    Expects a CSV with 'question' and 'explanation' columns (case-insensitive).
    Converts HTML to clean Markdown, preserving math formulas.
    """

    def __init__(self, question_col_hints=None, explanation_col_hints=None):
        self.question_col_hints = question_col_hints or ['question', 'q', 'query', 'problem']
        self.explanation_col_hints = explanation_col_hints or ['explanation', 'solution', 'answer', 'ans']
        
    def _find_column(self, columns: List[str], hints: List[str]) -> str:
        """Find the best matching column name based on hints."""
        cols_lower = {c.lower(): c for c in columns}
        
        # Exact matches first
        for hint in hints:
            if hint in cols_lower:
                return cols_lower[hint]
                
        # Partial matches
        for col in columns:
            col_lower = col.lower()
            for hint in hints:
                if hint in col_lower:
                    return col
                    
        return None

    def _html_to_markdown(self, html_text: str) -> str:
        """Convert HTML to Markdown safely, preserving math tags."""
        if not html_text or pd.isna(html_text):
            return ""
            
        text = str(html_text)
        
        # If no markdownify, fallback to basic tag stripping
        if md is None:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(text, 'html.parser')
            return soup.get_text(separator=' ', strip=True)
            
        # Use markdownify but disable stripping of math-like delimiters if any custom tags are used
        markdown_text = md(text, heading_style="ATX")
        
        # Clean up excessive newlines
        markdown_text = re.sub(r'\n{3,}', '\n\n', markdown_text)
        return markdown_text.strip()

    def process(self, file_path: str) -> Dict[str, Any]:
        """
        Process a CSV file containing HTML question and explanation pairs.
        """
        import tempfile
        import boto3
        from urllib.parse import urlparse
        import requests

        is_s3 = file_path.startswith("s3://")
        is_http = file_path.startswith("http://") or file_path.startswith("https://")
        
        if not is_s3 and not is_http and not os.path.exists(file_path):
            raise FileNotFoundError(f"CSV file not found: {file_path}")

        tmp_file = None
        try:
            if is_s3 or is_http:
                tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
                local_path = tmp_file.name
                
                if is_s3:
                    parsed = urlparse(file_path)
                    bucket = parsed.netloc
                    key = parsed.path.lstrip('/')
                    s3 = boto3.client('s3')
                    s3.download_file(bucket, key, local_path)
                else:
                    response = requests.get(file_path)
                    response.raise_for_status()
                    with open(local_path, "wb") as f:
                        f.write(response.content)
                
                process_path = local_path
            else:
                process_path = file_path

            # Read CSV
            try:
                df = pd.read_csv(process_path, encoding='utf-8')
            except UnicodeDecodeError:
                df = pd.read_csv(process_path, encoding='latin1')
                
            columns = list(df.columns)
            q_col = self._find_column(columns, self.question_col_hints)
            e_col = self._find_column(columns, self.explanation_col_hints)
            
            if not q_col:
                raise ValueError(f"Could not find a Question column in {file_path}. Available columns: {columns}")
            if not e_col:
                raise ValueError(f"Could not find an Explanation/Solution column in {file_path}. Available columns: {columns}")
                
            documents = []
            
            for idx, row in df.iterrows():
                raw_q = row[q_col]
                raw_e = row[e_col]
                
                if pd.isna(raw_q) and pd.isna(raw_e):
                    continue
                    
                clean_q = self._html_to_markdown(raw_q)
                clean_e = self._html_to_markdown(raw_e)
                
                combined_content = f"Question:
{clean_q}

Official Solution/Explanation:
{clean_e}"
                
                documents.append({
                    "content": combined_content,
                    "source": os.path.basename(file_path),
                    "row_index": idx,
                    "content_type": "csv_qa_pair",
                    "timestamp": datetime.now().isoformat()
                })
                
            if tmp_file:
                try:
                    os.unlink(tmp_file.name)
                except:
                    pass

            return {
                "documents": documents,
                "source": os.path.basename(file_path),
                "total_rows_processed": len(documents),
                "processed_at": datetime.now().isoformat()
            }
            
        except Exception as e:
            if tmp_file:
                try:
                    os.unlink(tmp_file.name)
                except:
                    pass
            logger.exception("Failed to process CSV")
            raise RuntimeError(f"Error processing CSV {file_path}: {str(e)}")
