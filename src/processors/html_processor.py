import requests
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
import re


class HTMLProcessor:
    def __init__(self):
        self._bs4 = None

    def _import_dependencies(self):
        if self._bs4 is None:
            try:
                from bs4 import BeautifulSoup

                self._bs4 = BeautifulSoup
            except ImportError:
                raise ImportError(
                    "beautifulsoup4 not installed. Run: pip install beautifulsoup4"
                )

    def process(self, file_path: str) -> Dict[str, Any]:
        self._import_dependencies()

        file_path_obj = Path(file_path)

        if not file_path_obj.exists():
            raise FileNotFoundError(f"HTML file not found: {file_path}")

        with open(file_path_obj, "r", encoding="utf-8") as f:
            html_content = f.read()

        return self._parse_html(html_content, str(file_path_obj.name))

    def process_url(self, url: str) -> Dict[str, Any]:
        self._import_dependencies()

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            html_content = response.text

            return self._parse_html(html_content, url)
        except Exception as e:
            raise RuntimeError(f"Error fetching URL {url}: {str(e)}")

    def _parse_html(self, html_content: str, source: str) -> Dict[str, Any]:
        soup = self._bs4(html_content, "html.parser")

        title = soup.title.string if soup.title else ""

        for script in soup(["script", "style"]):
            script.decompose()

        text_content = soup.get_text(separator="\n", strip=True)

        headings = []
        for level in range(1, 7):
            for heading in soup.find_all(f"h{level}"):
                headings.append({"level": level, "text": heading.get_text(strip=True)})

        links = []
        for link in soup.find_all("a", href=True):
            links.append({"text": link.get_text(strip=True), "href": link["href"]})

        documents = [
            {
                "content": text_content,
                "source": source,
                "title": title,
                "content_type": "html_text",
                "timestamp": datetime.now().isoformat(),
            }
        ]

        if headings:
            for heading in headings[:20]:
                documents.append(
                    {
                        "content": heading["text"],
                        "source": source,
                        "title": title,
                        "heading_level": heading["level"],
                        "content_type": "html_heading",
                        "timestamp": datetime.now().isoformat(),
                    }
                )

        return {
            "documents": documents,
            "source": source,
            "title": title,
            "heading_count": len(headings),
            "link_count": len(links),
            "processed_at": datetime.now().isoformat(),
        }

    def extract_main_content(
        self, html_content: str, source: str = "html"
    ) -> Dict[str, Any]:
        self._import_dependencies()

        soup = self._bs4(html_content, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        article = (
            soup.find("article")
            or soup.find("main")
            or soup.find("div", class_=re.compile("content|main|article"))
        )

        if article:
            main_content = article.get_text(separator="\n", strip=True)
        else:
            main_content = soup.get_text(separator="\n", strip=True)

        return {
            "documents": [
                {
                    "content": main_content,
                    "source": source,
                    "content_type": "html_main",
                    "timestamp": datetime.now().isoformat(),
                }
            ],
            "source": source,
            "processed_at": datetime.now().isoformat(),
        }
