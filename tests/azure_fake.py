"""A fake Azure Document Intelligence service for the tests (121, 279): it answers the REST requests the framework
sends (`jav/documents/azure_di.py`) without a network. Not a test module: the tests import it."""

from __future__ import annotations

import io
import json
import urllib.error

ENDPOINT = "https://example-di.cognitiveservices.azure.com/"
HOST = "example-di.cognitiveservices.azure.com"
OPERATION = f"https://{HOST}/documentintelligence/documentModels/prebuilt-read/analyzeResults/abc?api-version=2024-11-30"
WORDS = [{"content": "Payable", "polygon": [0.5, 1.0, 1.2, 1.0, 1.2, 1.15, 0.5, 1.15], "confidence": 0.99,
          "span": {"offset": 0, "length": 9}},
         {"content": "1000", "polygon": [1.3, 1.0, 1.8, 1.0, 1.8, 1.15, 1.3, 1.15], "confidence": 0.98,
          "span": {"offset": 10, "length": 4}}]


def result(pages: int = 1) -> dict:
    """A succeeded analysis with `pages` letter-size pages in inches, each with the same two words."""
    return {"status": "succeeded", "analyzeResult": {
        "apiVersion": "2024-11-30", "modelId": "prebuilt-read", "content": "Payable 1000",
        "pages": [{"pageNumber": n, "angle": 0, "width": 8.5, "height": 11, "unit": "inch", "words": WORDS,
                   "lines": [{"content": "Payable 1000"}]} for n in range(1, pages + 1)]}}


RESULT = result()
INFO = {"customDocumentModels": {"count": 0, "limit": 5000}}


class Reply(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200, headers: dict[str, str] | None = None) -> None:
        super().__init__(body)
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code: int, headers: dict[str, str] | None = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(ENDPOINT, code, "refused", headers or {}, io.BytesIO(b'{"error": {"code": "x"}}'))


class FakeAzure:
    """Answers the REST requests: POST …:analyze → 202 + Operation-Location (or the queued refusals in `post`); GET
    the result → the queued poll answers; GET …/info → the resource's details (or `info`, an error to raise)."""

    def __init__(self, polls: list | None = None, *, post: object = None, operation: str = OPERATION,
                 info: object = None) -> None:
        self.requests: list = []
        self.post_requests: list = []  # the analysis starts only, as they happen
        self.polls = list(polls if polls is not None else [{"status": "running"}, RESULT])
        self.post = list(post) if isinstance(post, list) else ([post] if post is not None else [])
        self.operation = operation
        self.info = info

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        if request.get_method() == "POST":
            self.post_requests.append(request)
            if self.post:
                refusal = self.post.pop(0)
                if isinstance(refusal, BaseException):
                    raise refusal
            return Reply(b"", 202, {"Operation-Location": self.operation, "Retry-After": "0"})
        if "/documentintelligence/info" in request.full_url:
            if isinstance(self.info, BaseException):
                raise self.info
            return Reply(json.dumps(self.info if self.info is not None else INFO).encode("utf-8"))
        answer = self.polls.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return Reply(json.dumps(answer).encode("utf-8"), 200, {"Retry-After": "0"})
