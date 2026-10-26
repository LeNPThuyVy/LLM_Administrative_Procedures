from .base_loader import BaseLoader, RawDocument


class WebLoader(BaseLoader):
    """
    Load nội dung web thành raw text.

    Lỗi mạng ở một URL không làm crash toàn bộ source.
    """

    def load(self, source_config: dict) -> list[RawDocument]:
        urls = source_config.get("urls", [])

        if isinstance(urls, str):
            urls = [urls]

        if not urls:
            return []

        documents = []

        for url in urls:
            try:
                from llama_index.readers.web import SimpleWebPageReader
                reader = SimpleWebPageReader(
                    html_to_text=True
                )

                parsed = reader.load_data(
                    urls=[url]
                )

                for doc in parsed:
                    documents.append(
                        RawDocument(
                            source_path=url,
                            raw_text=doc.text or "",
                            metadata={
                                **dict(doc.metadata or {}),
                                "source_url": url,
                            },
                        )
                    )

            except Exception as exc:
                print(
                    f"[web_loader] Skip {url}: {exc}"
                )

        return documents