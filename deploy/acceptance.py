"""Run safe HTTP smoke, load, security, and optional recovery/E2E checks."""

import argparse
import hashlib
import http.cookiejar
import json
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode


class Client:
    def __init__(self, api: str):
        self.api = api.rstrip("/")
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def request(self, method: str, path: str, payload=None, headers=None, timeout: int = 30):
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(self.api + path, data=data, method=method,
                                         headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers

    def login(self, owner_key: str) -> None:
        status, body, _ = self.request("POST", "/api/auth/login", {"key": owner_key})
        if status != 200 or json.loads(body).get("role") != "owner":
            raise RuntimeError("Owner login acceptance failed.")


def smoke(api: str, owner_key: str) -> tuple[Client, list[dict]]:
    client = Client(api)
    status, body, _ = client.request("GET", "/health/ready")
    if status != 200 or json.loads(body).get("status") != "ready":
        raise RuntimeError("Readiness acceptance failed.")
    if client.request("GET", "/api/documents")[0] != 401:
        raise RuntimeError("Private documents are reachable without a session.")
    client.login(owner_key)
    status, body, _ = client.request("GET", "/api/documents")
    if status != 200 or not isinstance(json.loads(body), list):
        raise RuntimeError("Authenticated document listing failed.")
    return client, json.loads(body)


def load_probe(api: str, count: int, max_p95_ms: float) -> dict:
    if not 1 <= count <= 1000:
        raise ValueError("Load request count must be 1 to 1000.")

    def probe(_):
        started = time.monotonic()
        status = Client(api).request("GET", "/health/live")[0]
        return status, (time.monotonic() - started) * 1000

    with ThreadPoolExecutor(max_workers=min(20, count)) as pool:
        results = list(pool.map(probe, range(count)))
    latencies = sorted(duration for _, duration in results)
    p95 = latencies[max(0, int(0.95 * len(latencies)) - 1)]
    if any(status != 200 for status, _ in results) or p95 > max_p95_ms:
        raise RuntimeError("Liveness load probe exceeded the error or latency target.")
    return {"requests": count, "p95_ms": round(p95, 1), "errors": 0}


def cross_workspace_probe(client: Client, other_api: str) -> None:
    cookie = next((item for item in client.cookies if item.name == "rag_owner"), None)
    if cookie is None:
        raise RuntimeError("Owner cookie missing after login.")
    target = Client(other_api)
    status, _, _ = target.request("GET", "/api/documents", headers={"Cookie": f"rag_owner={cookie.value}"})
    if status != 401:
        raise RuntimeError("A session from another workspace was accepted.")


def recovery_probe(source: Client, original: list[dict], recovered_api: str, owner_key: str) -> dict:
    recovered = Client(recovered_api)
    recovered.login(owner_key)
    status, body, _ = recovered.request("GET", "/api/documents")
    if status != 200:
        raise RuntimeError("Recovered document listing failed.")
    other = json.loads(body)
    if {item["id"] for item in original} != {item["id"] for item in other}:
        raise RuntimeError("Recovered registry document IDs differ.")
    checked = 0
    for document in other:
        if document.get("status") != "ready":
            continue
        path = f"/api/documents/{document['id']}/file"
        status, body, _ = recovered.request("GET", path, timeout=60)
        if status != 200 or not body:
            raise RuntimeError("A recovered original is unavailable.")
        source_status, source_body, _ = source.request("GET", path, timeout=60)
        if source_status != 200 or hashlib.sha256(source_body).digest() != hashlib.sha256(body).digest():
            raise RuntimeError("A recovered original differs from its source.")
        summary = recovered.request("GET", "/api/summaries?" + urlencode({
            "scope": "document", "document_id": document["id"]}), timeout=60)
        if summary[0] != 200:
            raise RuntimeError("Recovered vector evidence is unavailable.")
        checked += 1
    return {"registered_documents": len(other), "ready_originals_and_vectors_checked": checked}


def e2e_probe(client: Client, pdf: Path) -> dict:
    content = pdf.read_bytes()
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{pdf.name}\"\r\n"
            f"Content-Type: application/pdf\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(client.api + "/api/ingest-stream", data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with client.opener.open(request, timeout=900) as response:
        events = [json.loads(line[6:]) for line in response.read().decode().splitlines() if line.startswith("data: ")]
    completed = next((event for event in events if event.get("status") == "completed"), None)
    if not completed:
        raise RuntimeError("End-to-end ingestion did not complete.")
    document_id = completed["document_id"]
    try:
        status, original, _ = client.request("GET", f"/api/documents/{document_id}/pdf", timeout=60)
        if status != 200 or hashlib.sha256(original).digest() != hashlib.sha256(content).digest():
            raise RuntimeError("End-to-end source retrieval differs from the upload.")
        status, answer, _ = client.request("POST", "/api/chat", {"query": "Summarize this document.",
            "sources": [document_id]}, timeout=180)
        if status != 200 or "answer" not in json.loads(answer):
            raise RuntimeError("End-to-end answer generation failed.")
    finally:
        client.request("DELETE", f"/api/documents/{document_id}", timeout=60)
    return {"ingestion": "ready", "original": "verified", "query": "responded"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True)
    parser.add_argument("--owner-key-file", type=Path, required=True)
    parser.add_argument("--load-requests", type=int, default=0)
    parser.add_argument("--max-p95-ms", type=float, default=1000)
    parser.add_argument("--other-api")
    parser.add_argument("--recovered-api")
    parser.add_argument("--pdf", type=Path)
    args = parser.parse_args()
    key = args.owner_key_file.read_text().strip()
    client, documents = smoke(args.api, key)
    report = {"smoke": "passed", "registered_documents": len(documents)}
    if args.load_requests:
        report["load"] = load_probe(args.api, args.load_requests, args.max_p95_ms)
    if args.other_api:
        cross_workspace_probe(client, args.other_api)
        report["cross_workspace"] = "rejected"
    if args.recovered_api:
        report["recovery"] = recovery_probe(client, documents, args.recovered_api, key)
    if args.pdf:
        report["end_to_end"] = e2e_probe(client, args.pdf)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
