#!/usr/bin/env python3
"""Collect bounded public-doc evidence and render normalized Agent Native reports."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree


SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import audit  # noqa: E402
from safety import sanitize_data  # noqa: E402


SKILL_ROOT = SCRIPT_ROOT.parent
RUBRIC_PATH = SKILL_ROOT / "references" / "rubric.v1.json"
SOURCES_PATH = SKILL_ROOT / "references" / "sources.v1.json"
COLLECTOR_VERSION = "agent-native-evidence-collector.v1.0.1"
SAFE_RESPONSE_HEADERS = {"cache-control", "content-type", "etag", "expires", "last-modified"}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
DOC_CHECK_IDS = {
    item["id"] for item in json.loads(RUBRIC_PATH.read_text(encoding="utf-8"))["criteria"]
    if item["category"] == "Docs"
}


class UnsafeTargetError(ValueError):
    """The URL could reach a non-public or otherwise unsafe target."""


class CollectionLimitError(RuntimeError):
    """A hard collector limit was reached."""


class RequestBudget:
    def __init__(self, maximum: int):
        if not 1 <= maximum <= 64:
            raise ValueError("max_requests must be between 1 and 64")
        self.maximum = maximum
        self.used = 0

    def take(self) -> None:
        if self.used >= self.maximum:
            raise CollectionLimitError(f"request budget exhausted at {self.maximum}")
        self.used += 1


class CollectionLimits:
    def __init__(
        self,
        max_requests: int = 32,
        max_bytes: int = 1_000_000,
        timeout_seconds: float = 10.0,
        max_redirects: int = 4,
    ):
        if not 1 <= max_requests <= 64:
            raise ValueError("max_requests must be between 1 and 64")
        if not 1_024 <= max_bytes <= 2_000_000:
            raise ValueError("max_bytes must be between 1024 and 2000000")
        if not 1 <= timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be between 1 and 30")
        if not 0 <= max_redirects <= 5:
            raise ValueError("max_redirects must be between 0 and 5")
        self.max_requests = max_requests
        self.max_bytes = max_bytes
        self.timeout_seconds = timeout_seconds
        self.max_redirects = max_redirects

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_requests": self.max_requests,
            "max_bytes": self.max_bytes,
            "timeout_seconds": self.timeout_seconds,
            "max_redirects": self.max_redirects,
        }


class ResolvedTarget:
    def __init__(self, url: str, scheme: str, hostname: str, port: int, addresses: list[str]):
        self.url = url
        self.scheme = scheme
        self.hostname = hostname
        self.port = port
        self.addresses = tuple(addresses)

    @property
    def request_target(self) -> str:
        return quote(urlsplit(self.url).path or "/", safe="/%:@!$&'()*+,;=-._~")

    @property
    def host_header(self) -> str:
        host = f"[{self.hostname}]" if ":" in self.hostname else self.hostname
        default_port = 443 if self.scheme == "https" else 80
        return host if self.port == default_port else f"{host}:{self.port}"


class FetchResult:
    def __init__(
        self,
        requested_url: str,
        final_url: str,
        status: int,
        headers: dict[str, str],
        body: bytes,
        redirect_chain: list[str],
        error: str | None = None,
        truncated: bool = False,
        connected_ip: str | None = None,
    ):
        self.requested_url = requested_url
        self.final_url = final_url
        self.status = status
        self.headers = {str(key).lower(): str(value) for key, value in headers.items()}
        self.body = body
        self.redirect_chain = list(redirect_chain)
        self.error = error
        self.truncated = truncated
        self.connected_ip = connected_ip

    def metadata(self, accept: str | None = None) -> dict[str, Any]:
        return {
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "status": self.status,
            "accept": accept,
            "headers": {key: value for key, value in self.headers.items() if key in SAFE_RESPONSE_HEADERS},
            "bytes_captured": len(self.body),
            "body_sha256": hashlib.sha256(self.body).hexdigest(),
            "redirect_chain": self.redirect_chain,
            "connected_ip": self.connected_ip,
            "truncated": self.truncated,
            "error": self.error,
        }


def _resolved_addresses(hostname: str, port: int, resolver: Callable[..., Any]) -> list[str]:
    try:
        return sorted({str(item[4][0]) for item in resolver(hostname, port, type=socket.SOCK_STREAM)})
    except (OSError, socket.gaierror) as exc:
        raise UnsafeTargetError(f"target host did not resolve: {hostname}") from exc


def _normalize_http_url(value: str) -> tuple[str, str, str, int]:
    raw = str(value).strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise UnsafeTargetError("target URL is malformed") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafeTargetError("target URL must use http or https")
    if not parsed.hostname:
        raise UnsafeTargetError("target URL must include a host")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeTargetError("target URL must not contain userinfo")
    if "?" in raw:
        raise UnsafeTargetError("target URL must not contain a query string")
    if parsed.fragment:
        raise UnsafeTargetError("target URL must not contain a fragment")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in raw):
        raise UnsafeTargetError("target URL contains invalid control characters")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
        raise UnsafeTargetError("local and internal hostnames are not allowed")
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise UnsafeTargetError("target URL contains an invalid host") from exc
    host_netloc = f"[{hostname}]" if ":" in hostname else hostname
    netloc = host_netloc
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    if parsed.port and parsed.port != default_port:
        netloc = f"{host_netloc}:{parsed.port}"
    path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
    normalized = urlunsplit((parsed.scheme.lower(), netloc, path, "", ""))
    return normalized, parsed.scheme.lower(), hostname, port


def resolve_public_target(value: str, resolver: Callable[..., Any] = socket.getaddrinfo) -> ResolvedTarget:
    normalized, scheme, hostname, port = _normalize_http_url(value)
    try:
        literal = ipaddress.ip_address(hostname)
        addresses = [str(literal)]
    except ValueError:
        addresses = _resolved_addresses(hostname, port, resolver)
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise UnsafeTargetError("target must resolve only to globally routable addresses")
    return ResolvedTarget(normalized, scheme, hostname, port, addresses)


def validate_public_url(value: str, resolver: Callable[..., Any] = socket.getaddrinfo) -> str:
    return resolve_public_target(value, resolver=resolver).url


def _safe_url_reference(value: str) -> str:
    original = str(value)
    raw = original.strip()
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in original):
        raise UnsafeTargetError("URL reference contains invalid control characters")
    if "?" in raw:
        raise UnsafeTargetError("URL reference must not contain a query string")
    if "#" in raw:
        raise UnsafeTargetError("URL reference must not contain a fragment")
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise UnsafeTargetError("URL reference is malformed") from exc
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeTargetError("URL reference must not contain userinfo")
    return raw


class SafeFetcher:
    def __init__(
        self,
        limits: CollectionLimits | None = None,
        *,
        resolver: Callable[..., Any] = socket.getaddrinfo,
        socket_factory: Callable[..., Any] = socket.socket,
        ssl_context_factory: Callable[[], Any] = ssl.create_default_context,
    ):
        self.limits = limits or CollectionLimits()
        self.budget = RequestBudget(self.limits.max_requests)
        self.resolver = resolver
        self.socket_factory = socket_factory
        self.ssl_context_factory = ssl_context_factory

    def _read(self, response: http.client.HTTPResponse) -> tuple[bytes, bool]:
        body = response.read(self.limits.max_bytes + 1)
        return body[: self.limits.max_bytes], len(body) > self.limits.max_bytes

    def _open_socket(self, target: ResolvedTarget) -> tuple[Any, str]:
        address = target.addresses[0]
        family = socket.AF_INET6 if ipaddress.ip_address(address).version == 6 else socket.AF_INET
        sock = self.socket_factory(family, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.limits.timeout_seconds)
            connect_address = (address, target.port, 0, 0) if family == socket.AF_INET6 else (address, target.port)
            sock.connect(connect_address)
            if target.scheme == "https":
                sock = self.ssl_context_factory().wrap_socket(sock, server_hostname=target.hostname)
            return sock, address
        except Exception:
            sock.close()
            raise

    def _request_once(self, target: ResolvedTarget, accept: str | None) -> tuple[int, dict[str, str], str | None, bytes, bool, str]:
        chosen_accept = accept or "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1"
        if "\r" in chosen_accept or "\n" in chosen_accept:
            raise ValueError("accept header contains invalid control characters")
        sock, connected_ip = self._open_socket(target)
        try:
            request = (
                f"GET {target.request_target} HTTP/1.1\r\n"
                f"Host: {target.host_header}\r\n"
                f"Accept: {chosen_accept}\r\n"
                "User-Agent: apostl-agent-native-experience/1.0.1\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            sock.sendall(request)
            response = http.client.HTTPResponse(sock, method="GET")
            response.begin()
            try:
                body, truncated = self._read(response)
                headers = {
                    key.lower(): value
                    for key, value in response.getheaders()
                    if key.lower() in SAFE_RESPONSE_HEADERS
                }
                location = response.getheader("Location")
                return response.status, headers, location, body, truncated, connected_ip
            finally:
                response.close()
        finally:
            sock.close()

    def fetch(self, url: str, accept: str | None = None) -> FetchResult:
        target = resolve_public_target(url, resolver=self.resolver)
        requested_url = target.url
        redirect_chain: list[str] = []
        while True:
            self.budget.take()
            try:
                status, headers, location, body, truncated, connected_ip = self._request_once(target, accept)
            except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
                return FetchResult(
                    requested_url,
                    target.url,
                    0,
                    {},
                    b"",
                    redirect_chain,
                    error=f"network request failed ({type(exc).__name__})",
                )
            if status in REDIRECT_STATUSES and location:
                if len(redirect_chain) >= self.limits.max_redirects:
                    raise CollectionLimitError(f"redirect limit exhausted at {self.limits.max_redirects}")
                target = resolve_public_target(
                    urljoin(target.url, _safe_url_reference(location)),
                    resolver=self.resolver,
                )
                redirect_chain.append(target.url)
                continue
            error = None if 200 <= status < 400 else f"HTTP {status}"
            return FetchResult(
                requested_url,
                target.url,
                status,
                headers,
                body,
                redirect_chain,
                error=error,
                truncated=truncated,
                connected_ip=connected_ip,
            )


class _DocumentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str] = []
        self.headings: list[tuple[int, str]] = []
        self._heading_level: int | None = None
        self._heading_parts: list[str] = []
        self._ignored_depth = 0
        self.has_tabs = False
        self.first_h1_offset: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        if tag in {"script", "style", "noscript", "template"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag == "a" and attributes.get("href"):
            self.links.append(attributes["href"])
        classes = set(attributes.get("class", "").lower().split())
        if attributes.get("role", "").lower() in {"tab", "tablist", "tabpanel"} or any("tab" in item for item in classes):
            self.has_tabs = True
        if re.fullmatch(r"h[1-6]", tag):
            self._heading_level = int(tag[1])
            self._heading_parts = []
            if tag == "h1" and self.first_h1_offset is None:
                self.first_h1_offset = len("\n".join(self.parts))

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "template"} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if self._heading_level and tag == f"h{self._heading_level}":
            heading = " ".join(self._heading_parts).strip()
            if heading:
                self.headings.append((self._heading_level, heading))
            self._heading_level = None
            self._heading_parts = []

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        text = " ".join(data.split())
        if not text:
            return
        self.parts.append(text)
        if self._heading_level:
            self._heading_parts.append(text)

    @property
    def visible_text(self) -> str:
        return "\n".join(self.parts)


def _decode(body: bytes) -> str:
    return body.decode("utf-8", errors="replace")


def _content_type(response: FetchResult) -> str:
    return response.headers.get("content-type", "").split(";", 1)[0].strip().lower()


def _is_success(response: FetchResult) -> bool:
    return 200 <= response.status < 300 and not response.truncated


def _is_markdown(response: FetchResult) -> bool:
    content_type = _content_type(response)
    if content_type in {"text/markdown", "text/x-markdown", "application/markdown"}:
        return _is_success(response)
    if content_type == "text/plain" and not re.search(r"<\s*(?:html|body|head)\b", _decode(response.body), re.I):
        return _is_success(response)
    return False


def _markdown_like(response: FetchResult) -> bool:
    text = _decode(response.body)
    return _is_success(response) and not re.search(r"<\s*(?:html|body|head)\b", text, re.I) and bool(
        re.search(r"(?:^|\n)(?:#{1,6}\s|```|~~~|[-*]\s)|\[[^]]+\]\([^)]+\)", text)
    )


def _canonical(value: str) -> str:
    normalized, _scheme, _hostname, _port = _normalize_http_url(value)
    parsed = urlsplit(normalized)
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    netloc = (parsed.hostname or "").lower()
    if parsed.port and not ((parsed.scheme == "https" and parsed.port == 443) or (parsed.scheme == "http" and parsed.port == 80)):
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme.lower(), netloc, path, "", ""))


def _same_origin(first: str, second: str) -> bool:
    a, b = urlsplit(first), urlsplit(second)
    return (a.scheme.lower(), a.hostname, a.port) == (b.scheme.lower(), b.hostname, b.port)


def _absolute_links(base_url: str, values: list[str]) -> list[str]:
    links = []
    for value in values:
        try:
            absolute = urljoin(base_url, _safe_url_reference(value))
            canonical = _canonical(absolute)
        except (UnsafeTargetError, ValueError):
            continue
        if _same_origin(base_url, canonical):
            links.append(canonical)
    return sorted(set(links))


def _llms_links(response: FetchResult) -> list[str]:
    if not _is_success(response):
        return []
    values = re.findall(r"\[[^]]+\]\(([^)\s]+)(?:\s+['\"][^'\"]*['\"])?\)", _decode(response.body))
    return _absolute_links(response.final_url, values)


def _sitemap_links(response: FetchResult, target_url: str) -> list[str]:
    if not _is_success(response):
        return []
    try:
        root = ElementTree.fromstring(response.body)
    except ElementTree.ParseError:
        return []
    values = [element.text.strip() for element in root.iter() if element.tag.rsplit("}", 1)[-1] == "loc" and element.text]
    return _absolute_links(target_url, values)


def _markdown_fences_valid(text: str) -> bool:
    opened: tuple[str, int] | None = None
    for line in text.splitlines():
        match = re.match(r"^\s*(`{3,}|~{3,})", line)
        if not match:
            continue
        marker = match.group(1)
        kind = marker[0]
        length = len(marker)
        if opened is None:
            opened = (kind, length)
        elif opened[0] == kind and length >= opened[1]:
            opened = None
    return opened is None


def _size_status(characters: int) -> str:
    if characters < 50_000:
        return "pass"
    if characters <= 100_000:
        return "warn"
    return "fail"


def _cache_status(responses: list[FetchResult]) -> tuple[str, str]:
    if not responses:
        return "skip", "No llms.txt or Markdown response existed to evaluate."
    worst = "pass"
    evidence = []
    for response in responses:
        cache_control = response.headers.get("cache-control", "")
        validators = bool(response.headers.get("etag") or response.headers.get("last-modified"))
        match = re.search(r"(?:s-maxage|max-age)\s*=\s*(\d+)", cache_control, re.I)
        max_age = int(match.group(1)) if match else None
        if max_age is not None and max_age <= 3600:
            current = "pass"
        elif "must-revalidate" in cache_control.lower() and validators:
            current = "pass"
        elif max_age is not None and max_age <= 86_400:
            current = "warn"
        elif validators and not cache_control:
            current = "pass"
        else:
            current = "fail"
        if {"pass": 0, "warn": 1, "fail": 2}[current] > {"pass": 0, "warn": 1, "fail": 2}[worst]:
            worst = current
        evidence.append(f"{response.final_url}: cache-control={cache_control or 'missing'}, validators={'yes' if validators else 'no'}")
    return worst, "; ".join(evidence)


def _friction(identifier: str, title: str, observation: str, evidence: str, fix: str, verification: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "title": title,
        "category": "docs",
        "step": "bounded static evidence collection",
        "observation": observation,
        "severity": "medium",
        "evidence": evidence,
        "smallest_fix": fix,
        "next_verification": verification,
        "business_consequence": "Hypothesis: this friction reduces agent discovery or reliable content consumption.",
        "impact_type": "hypothesis",
        "metric": "agent_first_value_success_rate",
        "metric_owner": None,
        "owner": None,
        "dependencies": None,
        "rice": {"reach": None, "impact": None, "confidence": None, "effort": None},
    }


def collect_evidence(
    *,
    target_url: str,
    journey_name: str,
    activation_event: str,
    target_agent: str,
    mode: str,
    max_pages: int,
    fetcher,
    retrieved_at: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if mode not in {"sample", "full"}:
        raise ValueError("mode must be sample or full")
    if not 1 <= max_pages <= 50:
        raise ValueError("max_pages must be between 1 and 50")
    retrieved_at = retrieved_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    responses: list[dict[str, Any]] = []
    cache: dict[tuple[str, str | None], FetchResult] = {}

    def fetch(url: str, accept: str | None = None) -> FetchResult:
        key = (_canonical(url), accept)
        if key not in cache:
            cache[key] = fetcher.fetch(url, accept=accept)
            responses.append(cache[key].metadata(accept))
        return cache[key]

    target_url = _canonical(target_url)
    parsed = urlsplit(target_url)
    origin = urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))
    target = fetch(target_url)
    negotiated = fetch(target_url, "text/markdown")
    llms_candidates = [urljoin(origin, "llms.txt"), urljoin(origin, "llms-full.txt")]
    llms_responses = [fetch(url) for url in llms_candidates]
    sitemap = fetch(urljoin(origin, "sitemap.xml"))
    fetch(urljoin(origin, "robots.txt"))
    suffix_candidate = target_url + ".md"
    replaced_path = re.sub(r"\.[A-Za-z0-9]+$", ".md", parsed.path)
    replaced_candidate = urlunsplit((parsed.scheme, parsed.netloc, replaced_path, parsed.query, ""))
    markdown_urls = list(dict.fromkeys((suffix_candidate, replaced_candidate)))
    markdown_responses = [fetch(url) for url in markdown_urls]
    invalid_name = f"__agent_native_missing_{hashlib.sha256(target_url.encode()).hexdigest()[:10]}.html"
    invalid_url = urljoin(target_url.rsplit("/", 1)[0] + "/", invalid_name)
    invalid = fetch(invalid_url)

    parser = _DocumentParser()
    if _is_success(target):
        parser.feed(_decode(target.body))
    visible = parser.visible_text
    markdown_response = next((item for item in markdown_responses if _is_markdown(item)), None)
    if markdown_response is None and _is_markdown(negotiated):
        markdown_response = negotiated
    llms_response = next((item for item in llms_responses if _is_success(item) and _content_type(item) in {"text/plain", "text/markdown", "text/x-markdown"}), None)
    llms_links = _llms_links(llms_response) if llms_response else []
    sitemap_links = _sitemap_links(sitemap, target_url)
    navigation_links = _absolute_links(target_url, parser.links)

    limitations = [
        "The collector performs bounded static public-doc checks only; it does not execute the selected activation journey.",
        "Product criteria remain unknown until product/API evidence is supplied; human evidence remains not_run.",
        "Raw response bodies are analyzed in memory but not written to disk; raw metadata retains safe headers, hashes, byte counts, redirects, status, and truncation state.",
        "Each request connects to the first validated public address without retrying alternate addresses; a transient failure on that address can block collection.",
        "The bundled source registry is versioned but not refreshed automatically; refresh drift-prone guidance before calling it current.",
    ]

    base_prefix = parsed.path.rsplit("/", 1)[0] + "/"
    discovered = [target_url]
    for source in (llms_links, sitemap_links, navigation_links):
        for url in source:
            if urlsplit(url).path.startswith(base_prefix) and url not in discovered:
                discovered.append(url)
    actual_mode = mode
    if mode == "full" and len(discovered) > max_pages:
        actual_mode = "sample"
        limitations.append(
            f"Requested full mode discovered {len(discovered)} eligible same-section URLs, exceeding --max-pages {max_pages}; the collector downgraded to sample and did not claim full coverage."
        )
    guide_urls = discovered[:max_pages] if actual_mode == "full" else [target_url]
    corpus_rows = []
    for url in guide_urls:
        response = target if url == target_url else fetch(url)
        if 200 <= response.status < 300 and not response.truncated:
            terminal = "passed"
        elif response.status in {401, 403}:
            terminal = "blocked"
        elif response.status == 0:
            terminal = "blocked"
        else:
            terminal = "failed"
        sources = ["selected_url"] if url == target_url else []
        if url in llms_links:
            sources.append("llms.txt")
        if url in sitemap_links:
            sources.append("sitemap")
        if url in navigation_links:
            sources.append("navigation")
        corpus_rows.append({
            "url": url,
            "source": sources,
            "status": terminal,
            "redirect_chain": response.redirect_chain,
            "auth_gate": "present" if response.status in {401, 403} else "none",
            "content_hash": hashlib.sha256(response.body).hexdigest(),
            "blocker": response.error if terminal == "blocked" else None,
        })

    checks: dict[str, dict[str, Any]] = {}
    if llms_response is None:
        checks["llms-txt-exists"] = {"status": "fail", "evidence": "Canonical /llms.txt and /llms-full.txt did not return a usable text index."}
    else:
        canonical = _canonical(llms_response.requested_url) == _canonical(llms_candidates[0])
        checks["llms-txt-exists"] = {"status": "pass" if canonical else "warn", "evidence": f"Usable index: {llms_response.final_url}."}
    checks["llms-txt-valid"] = {
        "status": "skip" if llms_response is None else ("pass" if llms_links and re.search(r"(?m)^#\s+\S", _decode(llms_response.body)) else "fail"),
        "evidence": "Skipped because no usable index exists." if llms_response is None else f"Parsed {len(llms_links)} unique same-origin Markdown links.",
    }
    llms_chars = len(_decode(llms_response.body)) if llms_response else 0
    checks["llms-txt-size"] = {
        "status": "skip" if llms_response is None else _size_status(llms_chars),
        "evidence": "Skipped because no usable index exists." if llms_response is None else f"Index contains {llms_chars} characters.",
    }
    linked_responses = []
    if llms_response and len(llms_links) <= max_pages:
        linked_responses = [fetch(url) for url in llms_links]
        resolved = sum(_is_success(item) for item in linked_responses)
        checks["llms-txt-links-resolve"] = {
            "status": "pass" if resolved == len(linked_responses) else ("warn" if resolved else "fail"),
            "passed": resolved,
            "total": len(linked_responses),
            "evidence": f"Resolved {resolved} of {len(linked_responses)} bounded index links.",
        }
        markdown_count = sum(_is_markdown(item) for item in linked_responses)
        checks["llms-txt-links-markdown"] = {
            "status": "pass" if markdown_count == len(linked_responses) else ("warn" if markdown_count else "fail"),
            "passed": markdown_count,
            "total": len(linked_responses),
            "evidence": f"{markdown_count} of {len(linked_responses)} index links returned Markdown.",
        }
    elif llms_response:
        note = f"Index exposed {len(llms_links)} links, exceeding --max-pages {max_pages}; link checks were not run."
        checks["llms-txt-links-resolve"] = {"status": "not_run", "evidence": note}
        checks["llms-txt-links-markdown"] = {"status": "not_run", "evidence": note}
        limitations.append(note)
    else:
        checks["llms-txt-links-resolve"] = {"status": "skip", "evidence": "Skipped because no usable index exists."}
        checks["llms-txt-links-markdown"] = {"status": "skip", "evidence": "Skipped because no usable index exists."}

    html_has_directive = bool(re.search(r"llms(?:-full)?\.txt", _decode(target.body), re.I))
    checks["llms-txt-directive-html"] = {"status": "pass" if html_has_directive else "fail", "evidence": "Target HTML advertises llms.txt." if html_has_directive else "Target HTML contains no llms.txt discovery directive."}
    md_has_directive = bool(markdown_response and re.search(r"llms(?:-full)?\.txt", _decode(markdown_response.body), re.I))
    checks["llms-txt-directive-md"] = {"status": "pass" if md_has_directive else "fail", "evidence": "Markdown advertises llms.txt." if md_has_directive else "No available Markdown representation advertises llms.txt."}
    explicit_markdown = next((item for item in markdown_responses if _is_markdown(item)), None)
    if explicit_markdown:
        md_url_status = "pass"
        md_url_evidence = f"Stable Markdown URL: {explicit_markdown.final_url}."
    elif next((item for item in markdown_responses if _markdown_like(item)), None):
        md_url_status = "warn"
        md_url_evidence = "A deterministic URL returned Markdown-like content with a non-Markdown content type."
    else:
        md_url_status = "fail"
        md_url_evidence = "Tested deterministic Markdown URL variants were unavailable or returned HTML."
    checks["markdown-url-support"] = {"status": md_url_status, "evidence": md_url_evidence}
    if _is_markdown(negotiated):
        negotiation_status = "pass"
        negotiation_evidence = f"Accept: text/markdown returned {_content_type(negotiated)}."
    elif _markdown_like(negotiated):
        negotiation_status = "warn"
        negotiation_evidence = "Accept: text/markdown returned Markdown-like content with the wrong content type."
    else:
        negotiation_status = "fail"
        same = hashlib.sha256(negotiated.body).digest() == hashlib.sha256(target.body).digest()
        negotiation_evidence = f"Accept: text/markdown returned {_content_type(negotiated) or 'unknown content type'}; ordinary and negotiated bodies {'matched' if same else 'differed'}."
    checks["content-negotiation"] = {"status": negotiation_status, "evidence": negotiation_evidence}

    visible_chars = len(visible)
    if parser.headings and visible_chars >= 40:
        rendering_status = "pass"
    elif visible_chars:
        rendering_status = "warn"
    else:
        rendering_status = "fail"
    checks["rendering-strategy"] = {"status": rendering_status, "passed": 1 if rendering_status == "pass" else 0, "total": 1, "evidence": f"Raw HTML yielded {visible_chars} visible characters and {len(parser.headings)} headings without JavaScript."}
    if markdown_response:
        markdown_chars = len(_decode(markdown_response.body))
        checks["page-size-markdown"] = {"status": _size_status(markdown_chars), "passed": 1 if markdown_chars < 50_000 else 0, "total": 1, "evidence": f"Markdown representation contains {markdown_chars} characters."}
    else:
        checks["page-size-markdown"] = {"status": "skip", "evidence": "Skipped because no Markdown representation is available."}
    checks["page-size-html"] = {"status": _size_status(visible_chars), "passed": 1 if visible_chars < 50_000 else 0, "total": 1, "evidence": f"HTML visible-text serialization contains {visible_chars} characters; raw response captured {len(target.body)} bytes."}
    if visible_chars and parser.first_h1_offset is not None:
        start_percent = 100 * parser.first_h1_offset / visible_chars
        start_status = "pass" if start_percent <= 10 else ("warn" if start_percent <= 50 else "fail")
        start_evidence = f"First H1 begins at {start_percent:.2f}% of visible-text serialization."
    else:
        start_status = "unknown"
        start_evidence = "No H1 offset could be measured."
    checks["content-start-position"] = {"status": start_status, "evidence": start_evidence}
    checks["tabbed-content-serialization"] = {"status": _size_status(visible_chars), "passed": 1 if visible_chars < 50_000 else 0, "total": 1, "evidence": f"Tabbed content {'was' if parser.has_tabs else 'was not'} detected; serialized text contains {visible_chars} characters."}
    if not parser.has_tabs:
        section_status, section_evidence = "pass", "No tab groups were detected, so no generic tab-section headings were exposed."
    else:
        generic = sum(bool(re.fullmatch(r"(?:step|example|usage|install|setup)\s*\d*", text, re.I)) for _level, text in parser.headings)
        ratio = generic / len(parser.headings) if parser.headings else 1
        section_status = "pass" if ratio <= 0.25 else ("warn" if ratio <= 0.5 else "fail")
        section_evidence = f"{generic} of {len(parser.headings)} serialized tab headings were generic."
    checks["section-header-quality"] = {"status": section_status, "evidence": section_evidence}
    if markdown_response:
        fences_valid = _markdown_fences_valid(_decode(markdown_response.body))
        checks["markdown-code-fence-validity"] = {"status": "pass" if fences_valid else "fail", "evidence": "All Markdown fences closed." if fences_valid else "At least one Markdown fence was unclosed."}
    else:
        checks["markdown-code-fence-validity"] = {"status": "skip", "evidence": "Skipped because no Markdown representation is available."}
    if 400 <= invalid.status < 500:
        status_code_status = "pass"
    elif invalid.status == 202 or invalid.status >= 500 or invalid.status == 0:
        status_code_status = "warn"
    else:
        status_code_status = "fail"
    checks["http-status-codes"] = {"status": status_code_status, "evidence": f"Fabricated sibling URL returned HTTP {invalid.status}."}
    cross_host = any(not _same_origin(target_url, url) for url in target.redirect_chain)
    js_redirect = bool(re.search(r"<meta[^>]+http-equiv\s*=\s*['\"]?refresh", _decode(target.body), re.I))
    redirect_status = "fail" if js_redirect else ("warn" if cross_host else "pass")
    checks["redirect-behavior"] = {"status": redirect_status, "evidence": f"Observed {len(target.redirect_chain)} HTTP redirects; cross-host={'yes' if cross_host else 'no'}; JavaScript/meta redirect={'yes' if js_redirect else 'no'}."}
    if llms_response is None:
        checks["llms-txt-coverage"] = {"status": "skip", "evidence": "Skipped because no usable index exists."}
    elif sitemap_links:
        covered = len(set(sitemap_links) & set(llms_links))
        ratio = covered / len(sitemap_links)
        coverage_status = "pass" if ratio >= 0.95 else ("warn" if ratio >= 0.8 else "fail")
        checks["llms-txt-coverage"] = {"status": coverage_status, "passed": covered, "total": len(sitemap_links), "evidence": f"Index covers {covered} of {len(sitemap_links)} sitemap URLs."}
    else:
        checks["llms-txt-coverage"] = {"status": "unknown", "evidence": "No usable sitemap was available for coverage comparison."}
    if markdown_response:
        html_segments = set(re.findall(r"[A-Za-z0-9][^\n]{7,}", visible))
        markdown_text = _decode(markdown_response.body)
        present = sum(segment in markdown_text for segment in html_segments)
        missing_ratio = 1 - (present / len(html_segments)) if html_segments else 0
        parity_status = "pass" if missing_ratio < 0.05 else ("warn" if missing_ratio < 0.2 else "fail")
        checks["markdown-content-parity"] = {"status": parity_status, "passed": present, "total": len(html_segments), "evidence": f"Approximate normalized segment comparison found {missing_ratio:.1%} missing from Markdown."}
    else:
        checks["markdown-content-parity"] = {"status": "skip", "evidence": "Skipped because no Markdown representation is available."}
    agent_resources = ([llms_response] if llms_response else []) + ([markdown_response] if markdown_response else [])
    cache_status, cache_evidence = _cache_status(agent_resources)
    checks["cache-header-hygiene"] = {"status": cache_status, "evidence": cache_evidence}
    if target.status in {401, 403} or re.search(r"/(?:login|sign-in|signin)(?:/|$)", urlsplit(target.final_url).path, re.I):
        auth_status = "fail"
    elif _is_success(target):
        auth_status = "pass"
    else:
        auth_status = "warn"
    checks["auth-gate-detection"] = {"status": auth_status, "evidence": f"Signed-out target request returned HTTP {target.status} at {target.final_url}."}
    if auth_status == "pass":
        checks["auth-alternative-access"] = {"status": "not_applicable", "evidence": "The selected documentation path was public; no alternative was required."}
    else:
        usable_alternative = bool(llms_response or markdown_response)
        checks["auth-alternative-access"] = {"status": "pass" if usable_alternative else "fail", "evidence": "A public text alternative was available." if usable_alternative else "No public llms.txt or Markdown alternative was available."}

    if set(checks) != DOC_CHECK_IDS:
        missing = sorted(DOC_CHECK_IDS - set(checks))
        extra = sorted(set(checks) - DOC_CHECK_IDS)
        raise RuntimeError(f"collector/rubric drift: missing={missing}, extra={extra}")

    frictions = []
    if checks["llms-txt-exists"]["status"] == "fail":
        frictions.append(_friction("F-1", "No canonical llms.txt index", checks["llms-txt-exists"]["evidence"], "raw-evidence.json", "Publish a canonical root /llms.txt index.", "Fetch, parse, and resolve every frozen index link."))
    if checks["markdown-url-support"]["status"] == "fail" and checks["content-negotiation"]["status"] == "fail":
        frictions.append(_friction("F-2", "No deterministic Markdown representation", f"{md_url_evidence} {negotiation_evidence}", "raw-evidence.json", "Serve a stable Markdown URL or honor text/markdown negotiation.", "Verify content type, fences, size, and semantic parity."))
    if start_status in {"warn", "fail"}:
        frictions.append(_friction("F-3", "Primary content begins after boilerplate", start_evidence, "raw-evidence.json", "Move primary content earlier or provide Markdown.", "Confirm the first H1 begins within the first 10% of serialized content."))

    sources_registry = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    evidence = {
        "journey": {"name": journey_name, "target": target_agent, "activation_event": activation_event},
        "environment": {
            "collector": COLLECTOR_VERSION,
            "mode": "local_evidence_only",
            "requested_mode": mode,
            "afdocs_dependency": "not_required",
            "retrieved_at": retrieved_at,
        },
        "checks": checks,
        "agent_journey": {
            "status": "not_run",
            "activation_reached": False,
            "blocker": "The bounded static collector does not execute or infer the selected activation journey.",
            "steps": [],
        },
        "human_journey": {
            "mode": "selected",
            "selected_guide": journey_name,
            "status": "not_run",
            "next_action": "Have one representative human complete the same journey and record pre-activation evidence.",
        },
        "corpus": {"mode": actual_mode, "rows": corpus_rows},
        "frictions": frictions,
        "provenance": [
            {"url": target.final_url, "retrieved_at": retrieved_at, "version": f"SHA-256 {hashlib.sha256(target.body).hexdigest()}"},
            {"url": "local:references/rubric.v1.json", "retrieved_at": retrieved_at, "version": json.loads(RUBRIC_PATH.read_text(encoding="utf-8"))["rubric_version"]},
            {"url": "local:references/sources.v1.json", "retrieved_at": retrieved_at, "version": sources_registry["registry_version"]},
        ],
        "limitations": limitations,
        "public_artifacts": [],
    }
    configured_limits = fetcher.limits.as_dict() if hasattr(fetcher, "limits") else {
        "max_requests": fetcher.budget.maximum,
    }
    raw = {
        "collector": COLLECTOR_VERSION,
        "retrieved_at": retrieved_at,
        "limits": {**configured_limits, "max_pages": max_pages},
        "responses": responses,
        "inventory": {
            "llms_links": len(llms_links),
            "sitemap_links": len(sitemap_links),
            "navigation_links": len(navigation_links),
            "eligible_same_section_urls": len(discovered),
            "requested_mode": mode,
            "effective_mode": actual_mode,
            "max_pages": max_pages,
        },
    }
    return sanitize_data(evidence, reject_keys=True), sanitize_data(raw, reject_keys=True)


def run_collection(
    *,
    output_dir: Path,
    target_url: str,
    journey_name: str,
    activation_event: str,
    target_agent: str,
    mode: str,
    max_pages: int,
    fetcher=None,
    limits: CollectionLimits | None = None,
    retrieved_at: str | None = None,
) -> dict[str, Path]:
    limits = limits or CollectionLimits()
    fetcher = fetcher or SafeFetcher(limits)
    evidence, raw = collect_evidence(
        target_url=target_url,
        journey_name=journey_name,
        activation_event=activation_event,
        target_agent=target_agent,
        mode=mode,
        max_pages=max_pages,
        fetcher=fetcher,
        retrieved_at=retrieved_at,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = output_dir / "evidence.json"
    raw_path = output_dir / "raw-evidence.json"
    report_path = output_dir / "report.md"
    report_json_path = output_dir / "report.json"
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    raw_path.write_text(json.dumps(raw, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    report = audit.build_report(audit.load_json(RUBRIC_PATH), evidence)
    report_path.write_text(audit.render_markdown(report), encoding="utf-8")
    report_json_path.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"evidence": evidence_path, "raw": raw_path, "report": report_path, "report_json": report_json_path}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Public HTTP(S) documentation URL")
    parser.add_argument("--journey", required=True, help="Selected quickstart or journey")
    parser.add_argument("--activation-event", required=True, help="Observable activation promised by the journey")
    parser.add_argument("--target-agent", default="new coding agent")
    parser.add_argument("--mode", choices=("sample", "full"), default="sample")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--max-requests", type=int, default=32)
    parser.add_argument("--max-bytes", type=int, default=1_000_000)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--max-redirects", type=int, default=4)
    args = parser.parse_args()
    try:
        validated = _canonical(args.url)
        limits = CollectionLimits(args.max_requests, args.max_bytes, args.timeout_seconds, args.max_redirects)
        outputs = run_collection(
            output_dir=args.output_dir,
            target_url=validated,
            journey_name=args.journey,
            activation_event=args.activation_event,
            target_agent=args.target_agent,
            mode=args.mode,
            max_pages=args.max_pages,
            limits=limits,
        )
    except (UnsafeTargetError, CollectionLimitError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps({"status": "collected", "outputs": {key: str(value) for key, value in outputs.items()}}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
