import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime


class PDFProcessor:
    def __init__(self, ocr_enabled: bool = True, ocr_language: str = "eng+hin"):
        self.ocr_enabled = ocr_enabled
        self.ocr_language = ocr_language
        self._pymupdf = None
        self._pytesseract = None

    def _import_dependencies(self):
        if self._pymupdf is None:
            try:
                import fitz

                self._pymupdf = fitz
            except ImportError:
                raise ImportError(
                    "PyMuPDF (fitz) not installed. Run: pip install pymupdf"
                )

        if self.ocr_enabled:
            if self._pytesseract is None:
                try:
                    import pytesseract

                    self._pytesseract = pytesseract
                except ImportError:
                    pass

    def process(self, file_path: str) -> Dict[str, Any]:
        self._import_dependencies()

        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            raise FileNotFoundError(f"PDF file not found: {file_path}")

        documents = []

        try:
            doc = self._pymupdf.open(str(file_path))
            for page_num, page in enumerate(doc):
                text = page.get_text()

                if text.strip():
                    documents.append(
                        {
                            "content": text,
                            "source": str(file_path_obj.name),
                            "page": page_num + 1,
                            "content_type": "pdf_text",
                            "timestamp": datetime.now().isoformat(),
                        }
                    )
                elif self.ocr_enabled:
                    ocr_text = self._process_ocr(page, page_num + 1, file_path_obj.name)
                    if ocr_text:
                        documents.append(ocr_text)

            doc.close()
        except Exception as e:
            raise RuntimeError(f"Error processing PDF {file_path}: {str(e)}")

        return {
            "documents": documents,
            "source": str(file_path_obj.name),
            "total_pages": len(documents),
            "processed_at": datetime.now().isoformat(),
        }

    def _process_ocr(
        self, page, page_num: int, source: str
    ) -> Optional[Dict[str, Any]]:
        try:
            pix = page.get_pixmap(matrix=self._pymupdf.Matrix(2, 2))
            img_data = pix.tobytes("png")

            from PIL import Image
            import io

            image = Image.open(io.BytesIO(img_data))
            text = self._pytesseract.image_to_string(image, lang=self.ocr_language)

            if text.strip():
                return {
                    "content": text,
                    "source": source,
                    "page": page_num,
                    "content_type": "pdf_ocr",
                    "timestamp": datetime.now().isoformat(),
                }
        except Exception:
            pass

        return None


class DocumentChunker:
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_documents(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

        chunked_docs = []
        for doc in documents:
            content = doc.get("content", "")
            if not content:
                continue

            chunks = splitter.split_text(content)
            for i, chunk in enumerate(chunks):
                chunked_docs.append(
                    {
                        "content": chunk,
                        "source": doc.get("source", ""),
                        "page": doc.get("page", 0),
                        "chunk_id": i,
                        "content_type": doc.get("content_type", "text"),
                        "timestamp": doc.get("timestamp", ""),
                    }
                )

        return chunked_docs
