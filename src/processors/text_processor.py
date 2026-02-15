from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime
import re


class TextProcessor:
    def __init__(self):
        pass

    def process(self, file_path: str) -> Dict[str, Any]:
        file_path_obj = Path(file_path)

        if not file_path_obj.exists():
            raise FileNotFoundError(f"Text file not found: {file_path}")

        try:
            with open(file_path_obj, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(file_path_obj, "r", encoding="latin-1") as f:
                content = f.read()

        return {
            "documents": [
                {
                    "content": content,
                    "source": str(file_path_obj.name),
                    "content_type": "text",
                    "timestamp": datetime.now().isoformat(),
                }
            ],
            "source": str(file_path_obj.name),
            "char_count": len(content),
            "processed_at": datetime.now().isoformat(),
        }

    def process_raw(self, text: str, source: str = "raw_text") -> Dict[str, Any]:
        return {
            "documents": [
                {
                    "content": text,
                    "source": source,
                    "content_type": "text",
                    "timestamp": datetime.now().isoformat(),
                }
            ],
            "source": source,
            "char_count": len(text),
            "processed_at": datetime.now().isoformat(),
        }

    def process_lines(self, file_path: str, group_size: int = 5) -> Dict[str, Any]:
        file_path_obj = Path(file_path)

        if not file_path_obj.exists():
            raise FileNotFoundError(f"Text file not found: {file_path}")

        with open(file_path_obj, "r", encoding="utf-8") as f:
            lines = f.readlines()

        documents = []
        for i in range(0, len(lines), group_size):
            group = lines[i : i + group_size]
            content = "".join(group)

            if content.strip():
                documents.append(
                    {
                        "content": content,
                        "source": str(file_path_obj.name),
                        "line_start": i + 1,
                        "line_end": min(i + group_size, len(lines)),
                        "content_type": "text_lines",
                        "timestamp": datetime.now().isoformat(),
                    }
                )

        return {
            "documents": documents,
            "source": str(file_path_obj.name),
            "total_lines": len(lines),
            "processed_at": datetime.now().isoformat(),
        }


class MarkdownProcessor(TextProcessor):
    def __init__(self):
        super().__init__()

    def process(self, file_path: str) -> Dict[str, Any]:
        file_path_obj = Path(file_path)

        if not file_path_obj.exists():
            raise FileNotFoundError(f"Markdown file not found: {file_path}")

        with open(file_path_obj, "r", encoding="utf-8") as f:
            content = f.read()

        sections = self._extract_sections(content)

        documents = []
        for section in sections:
            documents.append(
                {
                    "content": section["content"],
                    "source": str(file_path_obj.name),
                    "section": section.get("heading", ""),
                    "content_type": "markdown",
                    "timestamp": datetime.now().isoformat(),
                }
            )

        if not documents:
            documents.append(
                {
                    "content": content,
                    "source": str(file_path_obj.name),
                    "content_type": "markdown",
                    "timestamp": datetime.now().isoformat(),
                }
            )

        return {
            "documents": documents,
            "source": str(file_path_obj.name),
            "sections": len(sections),
            "processed_at": datetime.now().isoformat(),
        }

    def _extract_sections(self, content: str) -> List[Dict[str, str]]:
        sections = []
        lines = content.split("\n")
        current_heading = ""
        current_content = []

        heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")

        for line in lines:
            match = heading_pattern.match(line)
            if match:
                if current_content:
                    sections.append(
                        {
                            "heading": current_heading,
                            "content": "\n".join(current_content).strip(),
                        }
                    )
                current_heading = match.group(2)
                current_content = []
            else:
                current_content.append(line)

        if current_content:
            sections.append(
                {
                    "heading": current_heading,
                    "content": "\n".join(current_content).strip(),
                }
            )

        return sections
