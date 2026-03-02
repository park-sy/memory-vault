#!/usr/bin/env python3
"""web-search.py — Multi-backend Web Search CLI

9개 백엔드(DDG, Naver, Google, Wikipedia, HackerNews, Reddit, RSS, GitHub)를
통합하는 검색 도구. 외부 유료 API 없이 실시간 웹 검색 수행.

Usage:
    web-search.py search "query" [--backend ddg,naver,hn] [--max-results 10]
                                 [--fetch-content] [--fetch-top 3] [--format json|markdown|jsonl]
    web-search.py fetch  "url"   [--max-chars 5000] [--format json|markdown|text]
    web-search.py fetch-batch url1 url2 ... [--max-chars 3000]
    web-search.py feed   "feed-url" [--since 24h] [--max-results 20]
    web-search.py hn     "query" [--limit 10] [--sort relevance|date|points]
    web-search.py reddit "query" [--subreddit all] [--limit 10] [--sort relevance|top]
    web-search.py naver  "query" [--type web|blog|news|image] [--limit 10]
    web-search.py google "query" [--limit 10] [--delay 5]
    web-search.py github "query" [--type repos|code|issues] [--limit 10]
    web-search.py backends
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Callable

# ── Data Models (frozen) ──────────────────────────────────────

@dataclass(frozen=True)
class SearchResult:
    """검색 결과 단일 항목."""
    title: str
    url: str
    snippet: str
    source: str       # "ddg"|"google"|"naver"|"wiki"|"hn"|"reddit"|"feed"|"github"
    rank: int = 0
    timestamp: str = ""
    score: float = 0.0


@dataclass(frozen=True)
class FetchedContent:
    """URL에서 추출한 콘텐츠."""
    url: str
    title: str
    text: str
    word_count: int
    fetched_at: str
    error: str = ""


@dataclass(frozen=True)
class SearchResponse:
    """통합 검색 응답."""
    query: str
    timestamp: str
    results: tuple[SearchResult, ...] = ()
    fetched_content: tuple[FetchedContent, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Backend Registry ──────────────────────────────────────────

BACKEND_REGISTRY: dict[str, Callable] = {}

BACKEND_WEIGHTS: dict[str, float] = {
    "naver": 1.3,
    "wiki": 1.2,
    "google": 1.1,
    "ddg": 1.0,
    "github": 1.0,
    "hn": 0.9,
    "reddit": 0.8,
    "feed": 0.7,
}


def _register(name: str):
    """백엔드 등록 데코레이터."""
    def decorator(func: Callable):
        BACKEND_REGISTRY[name] = func
        return func
    return decorator


def _make_request(url: str, headers: dict | None = None, timeout: int = 15) -> bytes:
    """stdlib urllib로 HTTP GET 요청."""
    hdrs = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/json,*/*",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── DDG Backend ───────────────────────────────────────────────

@_register("ddg")
def _search_ddg(query: str, max_results: int = 10) -> list[SearchResult]:
    """DuckDuckGo 검색. duckduckgo-search 패키지 필요."""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return []

    results = []
    try:
        with DDGS() as ddgs:
            for i, r in enumerate(ddgs.text(query, max_results=max_results)):
                results.append(SearchResult(
                    title=r.get("title", ""),
                    url=r.get("href", r.get("link", "")),
                    snippet=r.get("body", ""),
                    source="ddg",
                    rank=i + 1,
                ))
    except Exception:
        pass
    return results


# ── Naver Backend ─────────────────────────────────────────────

@_register("naver")
def _search_naver(
    query: str,
    max_results: int = 10,
    search_type: str = "webkr",
) -> list[SearchResult]:
    """네이버 오픈 API. NAVER_CLIENT_ID, NAVER_CLIENT_SECRET 환경변수 필요."""
    client_id = os.environ.get("NAVER_CLIENT_ID", "")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return []

    type_map = {"web": "webkr", "blog": "blog", "news": "news", "image": "image"}
    api_type = type_map.get(search_type, search_type)

    url = (
        f"https://openapi.naver.com/v1/search/{api_type}"
        f"?query={urllib.parse.quote(query)}"
        f"&display={min(max_results, 100)}"
        f"&start=1"
    )
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }

    results = []
    try:
        data = json.loads(_make_request(url, headers=headers))
        for i, item in enumerate(data.get("items", [])):
            # HTML 태그 제거 (네이버 응답에 <b> 등 포함)
            title = _strip_html(item.get("title", ""))
            snippet = _strip_html(item.get("description", ""))
            link = item.get("link", item.get("originallink", ""))
            ts = item.get("pubDate", "")

            results.append(SearchResult(
                title=title,
                url=link,
                snippet=snippet,
                source="naver",
                rank=i + 1,
                timestamp=ts,
            ))
    except Exception:
        pass
    return results


def _strip_html(text: str) -> str:
    """간단한 HTML 태그 제거."""
    import re
    return re.sub(r"<[^>]+>", "", text).strip()


# ── Google Backend ────────────────────────────────────────────

@_register("google")
def _search_google(query: str, max_results: int = 10, delay: float = 5.0) -> list[SearchResult]:
    """googlesearch-python. 차단 위험 완화: 요청 간 딜레이."""
    try:
        from googlesearch import search as gsearch
    except ImportError:
        return []

    results = []
    try:
        for i, url in enumerate(gsearch(query, num_results=max_results, sleep_interval=delay)):
            results.append(SearchResult(
                title="",  # googlesearch-python은 제목 미제공
                url=url,
                snippet="",
                source="google",
                rank=i + 1,
            ))
    except Exception:
        pass
    return results


# ── Wikipedia Backend ─────────────────────────────────────────

@_register("wiki")
def _search_wiki(query: str, max_results: int = 5) -> list[SearchResult]:
    """Wikipedia 검색. wikipedia 패키지 필요."""
    try:
        import wikipedia
    except ImportError:
        return []

    results = []
    try:
        titles = wikipedia.search(query, results=max_results)
        for i, title in enumerate(titles):
            try:
                page = wikipedia.page(title, auto_suggest=False)
                results.append(SearchResult(
                    title=page.title,
                    url=page.url,
                    snippet=page.summary[:300],
                    source="wiki",
                    rank=i + 1,
                ))
            except (wikipedia.DisambiguationError, wikipedia.PageError):
                continue
    except Exception:
        pass
    return results


# ── HackerNews Backend ───────────────────────────────────────

@_register("hn")
def _search_hn(
    query: str,
    max_results: int = 10,
    sort: str = "relevance",
) -> list[SearchResult]:
    """HackerNews Algolia 공개 API."""
    sort_map = {
        "relevance": "search",
        "date": "search_by_date",
        "points": "search",
    }
    endpoint = sort_map.get(sort, "search")
    url = (
        f"https://hn.algolia.com/api/v1/{endpoint}"
        f"?query={urllib.parse.quote(query)}"
        f"&hitsPerPage={max_results}"
        f"&tags=story"
    )

    results = []
    try:
        data = json.loads(_make_request(url))
        hits = data.get("hits", [])

        if sort == "points":
            hits = sorted(hits, key=lambda h: h.get("points", 0), reverse=True)

        for i, hit in enumerate(hits[:max_results]):
            story_url = hit.get("url", "")
            if not story_url:
                story_url = f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"

            results.append(SearchResult(
                title=hit.get("title", ""),
                url=story_url,
                snippet=f"Points: {hit.get('points', 0)} | "
                        f"Comments: {hit.get('num_comments', 0)}",
                source="hn",
                rank=i + 1,
                timestamp=hit.get("created_at", ""),
                score=float(hit.get("points", 0)),
            ))
    except Exception:
        pass
    return results


# ── Reddit Backend ────────────────────────────────────────────

@_register("reddit")
def _search_reddit(
    query: str,
    max_results: int = 10,
    subreddit: str = "all",
    sort: str = "relevance",
) -> list[SearchResult]:
    """Reddit .json 엔드포인트."""
    url = (
        f"https://www.reddit.com/r/{subreddit}/search.json"
        f"?q={urllib.parse.quote(query)}"
        f"&sort={sort}"
        f"&limit={max_results}"
        f"&restrict_sr=0"
        f"&t=year"
    )

    results = []
    try:
        data = json.loads(_make_request(url))
        children = data.get("data", {}).get("children", [])
        for i, child in enumerate(children):
            post = child.get("data", {})
            results.append(SearchResult(
                title=post.get("title", ""),
                url=f"https://reddit.com{post.get('permalink', '')}",
                snippet=post.get("selftext", "")[:300],
                source="reddit",
                rank=i + 1,
                timestamp=datetime.fromtimestamp(
                    post.get("created_utc", 0), tz=timezone.utc
                ).isoformat() if post.get("created_utc") else "",
                score=float(post.get("score", 0)),
            ))
    except Exception:
        pass
    return results


# ── Feed (RSS/Atom) Backend ──────────────────────────────────

@_register("feed")
def _search_feed(
    feed_url: str,
    max_results: int = 20,
    since_hours: int = 24,
) -> list[SearchResult]:
    """RSS/Atom 피드 파싱. feedparser 패키지 필요."""
    try:
        import feedparser
    except ImportError:
        return []

    results = []
    try:
        feed = feedparser.parse(feed_url)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)

        for i, entry in enumerate(feed.entries[:max_results]):
            published = ""
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                if dt < cutoff:
                    continue
                published = dt.isoformat()

            results.append(SearchResult(
                title=entry.get("title", ""),
                url=entry.get("link", ""),
                snippet=_strip_html(entry.get("summary", ""))[:300],
                source="feed",
                rank=i + 1,
                timestamp=published,
            ))
    except Exception:
        pass
    return results


# ── GitHub Backend ────────────────────────────────────────────

@_register("github")
def _search_github(
    query: str,
    max_results: int = 10,
    search_type: str = "repositories",
) -> list[SearchResult]:
    """gh api search. gh CLI 필요."""
    type_map = {"repos": "repositories", "code": "code", "issues": "issues"}
    api_type = type_map.get(search_type, search_type)

    results = []
    try:
        cmd = [
            "gh", "api",
            f"search/{api_type}",
            "-X", "GET",
            "-f", f"q={query}",
            "-f", f"per_page={max_results}",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            return []

        data = json.loads(proc.stdout)
        items = data.get("items", [])
        for i, item in enumerate(items):
            if api_type == "repositories":
                title = item.get("full_name", "")
                url = item.get("html_url", "")
                snippet = item.get("description", "") or ""
                snippet += f" | Stars: {item.get('stargazers_count', 0)}"
                sc = float(item.get("stargazers_count", 0))
            elif api_type == "code":
                title = item.get("name", "")
                url = item.get("html_url", "")
                repo = item.get("repository", {})
                snippet = f"Repo: {repo.get('full_name', '')} | Path: {item.get('path', '')}"
                sc = 0.0
            else:  # issues
                title = item.get("title", "")
                url = item.get("html_url", "")
                snippet = (item.get("body", "") or "")[:300]
                sc = float(item.get("comments", 0))

            results.append(SearchResult(
                title=title,
                url=url,
                snippet=snippet[:300],
                source="github",
                rank=i + 1,
                score=sc,
            ))
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass
    return results


# ── Content Extraction ────────────────────────────────────────

class _BasicHTMLStripper(HTMLParser):
    """stdlib 기반 HTML 태그 제거 (script/style/nav/footer 건너뜀)."""

    SKIP_TAGS = frozenset({"script", "style", "nav", "footer", "header", "aside", "noscript"})

    def __init__(self):
        super().__init__()
        self._pieces: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag.lower() in self.SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            stripped = data.strip()
            if stripped:
                self._pieces.append(stripped)

    def get_text(self) -> str:
        return "\n".join(self._pieces)


def _extract_content(html: str, url: str = "") -> tuple[str, str]:
    """콘텐츠 추출. trafilatura 우선, stdlib 폴백.
    Returns: (title, text)
    """
    # 1단계: trafilatura 시도
    try:
        import trafilatura
        result = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            favor_precision=True,
            url=url,
        )
        if result:
            # 제목 추출 시도
            metadata = trafilatura.extract(
                html, output_format="json", url=url,
            )
            title = ""
            if metadata:
                try:
                    title = json.loads(metadata).get("title", "")
                except (json.JSONDecodeError, TypeError):
                    pass
            return title, result
    except ImportError:
        pass
    except Exception:
        pass

    # 2단계: stdlib HTMLParser 폴백
    title = ""
    import re
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if title_match:
        title = _strip_html(title_match.group(1)).strip()

    stripper = _BasicHTMLStripper()
    try:
        stripper.feed(html)
        return title, stripper.get_text()
    except Exception:
        return title, ""


def fetch_url(url: str, max_chars: int = 5000) -> FetchedContent:
    """URL에서 콘텐츠 추출."""
    try:
        raw = _make_request(url, timeout=20)
        html = raw.decode("utf-8", errors="replace")
        title, text = _extract_content(html, url)
        text = text[:max_chars] if max_chars > 0 else text
        return FetchedContent(
            url=url,
            title=title,
            text=text,
            word_count=len(text.split()),
            fetched_at=_now_iso(),
        )
    except Exception as e:
        return FetchedContent(
            url=url,
            title="",
            text="",
            word_count=0,
            fetched_at=_now_iso(),
            error=str(e),
        )


# ── Result Merging / Ranking ─────────────────────────────────

def _merge_results(
    all_results: list[SearchResult],
) -> list[SearchResult]:
    """다중 백엔드 결과 병합: URL 중복 제거 + 가중 점수 재정렬."""
    seen_urls: dict[str, SearchResult] = {}
    scored: list[tuple[float, SearchResult]] = []

    for r in all_results:
        normalized = r.url.rstrip("/").lower()
        if normalized in seen_urls:
            continue
        seen_urls[normalized] = r

        weight = BACKEND_WEIGHTS.get(r.source, 1.0)
        rank_score = (1.0 / max(r.rank, 1)) * weight
        explicit_score = r.score / 1000.0 if r.score > 0 else 0.0
        final_score = rank_score + explicit_score

        scored.append((final_score, r))

    scored.sort(key=lambda x: x[0], reverse=True)

    merged = []
    for i, (sc, r) in enumerate(scored):
        merged.append(SearchResult(
            title=r.title,
            url=r.url,
            snippet=r.snippet,
            source=r.source,
            rank=i + 1,
            timestamp=r.timestamp,
            score=round(sc, 4),
        ))
    return merged


# ── Output Formatting ─────────────────────────────────────────

def _format_json(response: SearchResponse) -> str:
    """JSON 출력."""
    def _to_dict(obj):
        if isinstance(obj, (SearchResult, FetchedContent)):
            return asdict(obj)
        if isinstance(obj, SearchResponse):
            d = {
                "query": obj.query,
                "timestamp": obj.timestamp,
                "results": [asdict(r) for r in obj.results],
                "fetched_content": [asdict(f) for f in obj.fetched_content],
                "metadata": obj.metadata,
            }
            return d
        return obj
    return json.dumps(_to_dict(response), ensure_ascii=False, indent=2)


def _format_markdown(response: SearchResponse) -> str:
    """Markdown 출력."""
    lines = [f"# Search: {response.query}", f"__{response.timestamp}__", ""]

    if response.results:
        lines.append(f"## Results ({len(response.results)})")
        for r in response.results:
            src_badge = f"[{r.source}]"
            lines.append(f"{r.rank}. {src_badge} **{r.title or r.url}**")
            lines.append(f"   {r.url}")
            if r.snippet:
                lines.append(f"   > {r.snippet[:200]}")
            lines.append("")

    if response.fetched_content:
        lines.append("## Fetched Content")
        for f in response.fetched_content:
            lines.append(f"### {f.title or f.url}")
            lines.append(f"_URL: {f.url} | Words: {f.word_count}_")
            if f.error:
                lines.append(f"**Error:** {f.error}")
            else:
                lines.append(f.text[:2000])
            lines.append("")

    meta = response.metadata
    if meta:
        lines.append("---")
        if meta.get("backends_used"):
            lines.append(f"Backends: {', '.join(meta['backends_used'])}")
        if meta.get("backends_failed"):
            lines.append(f"Failed: {meta['backends_failed']}")
        lines.append(f"Total: {meta.get('total_results', len(response.results))}")

    return "\n".join(lines)


def _format_jsonl(response: SearchResponse) -> str:
    """JSONL 출력 (결과당 1줄)."""
    lines = []
    for r in response.results:
        lines.append(json.dumps(asdict(r), ensure_ascii=False))
    return "\n".join(lines)


def _output(response: SearchResponse, fmt: str) -> None:
    """포맷에 맞춰 stdout 출력."""
    formatters = {"json": _format_json, "markdown": _format_markdown, "jsonl": _format_jsonl}
    formatter = formatters.get(fmt, _format_json)
    print(formatter(response))


# ── Command Handlers ──────────────────────────────────────────

def cmd_search(args: argparse.Namespace) -> None:
    """다중 백엔드 통합 검색."""
    backends = [b.strip() for b in args.backend.split(",")]
    all_results: list[SearchResult] = []
    failed: dict[str, str] = {}

    for backend_name in backends:
        fn = BACKEND_REGISTRY.get(backend_name)
        if fn is None:
            failed[backend_name] = "unknown backend"
            continue
        try:
            results = fn(args.query, max_results=args.max_results)
            all_results.extend(results)
        except Exception as e:
            failed[backend_name] = str(e)

    merged = _merge_results(all_results)
    dedup_count = len(all_results) - len(merged)

    # 콘텐츠 추출
    fetched: list[FetchedContent] = []
    if args.fetch_content or args.fetch_top > 0:
        top_n = args.fetch_top if args.fetch_top > 0 else len(merged)
        for r in merged[:top_n]:
            if r.url:
                fetched.append(fetch_url(r.url, max_chars=args.max_chars))

    response = SearchResponse(
        query=args.query,
        timestamp=_now_iso(),
        results=tuple(merged),
        fetched_content=tuple(fetched),
        metadata={
            "backends_used": backends,
            "backends_failed": failed,
            "total_results": len(merged),
            "deduplicated": dedup_count,
        },
    )
    _output(response, args.format)


def cmd_fetch(args: argparse.Namespace) -> None:
    """단일 URL 콘텐츠 추출."""
    content = fetch_url(args.url, max_chars=args.max_chars)
    response = SearchResponse(
        query=args.url,
        timestamp=_now_iso(),
        fetched_content=(content,),
        metadata={"backends_used": ["fetch"]},
    )
    _output(response, args.format)


def cmd_fetch_batch(args: argparse.Namespace) -> None:
    """다수 URL 콘텐츠 추출."""
    fetched = [fetch_url(u, max_chars=args.max_chars) for u in args.urls]
    response = SearchResponse(
        query=f"batch({len(args.urls)} urls)",
        timestamp=_now_iso(),
        fetched_content=tuple(fetched),
        metadata={"backends_used": ["fetch"], "total_results": len(fetched)},
    )
    _output(response, args.format)


def cmd_feed(args: argparse.Namespace) -> None:
    """RSS/Atom 피드 수집."""
    since_hours = _parse_since(args.since)
    results = _search_feed(args.feed_url, max_results=args.max_results, since_hours=since_hours)
    response = SearchResponse(
        query=args.feed_url,
        timestamp=_now_iso(),
        results=tuple(results),
        metadata={"backends_used": ["feed"], "total_results": len(results)},
    )
    _output(response, args.format)


def cmd_hn(args: argparse.Namespace) -> None:
    """HackerNews 검색."""
    results = _search_hn(args.query, max_results=args.limit, sort=args.sort)
    response = SearchResponse(
        query=args.query,
        timestamp=_now_iso(),
        results=tuple(results),
        metadata={"backends_used": ["hn"], "total_results": len(results)},
    )
    _output(response, args.format)


def cmd_reddit(args: argparse.Namespace) -> None:
    """Reddit 검색."""
    results = _search_reddit(
        args.query, max_results=args.limit,
        subreddit=args.subreddit, sort=args.sort,
    )
    response = SearchResponse(
        query=args.query,
        timestamp=_now_iso(),
        results=tuple(results),
        metadata={"backends_used": ["reddit"], "total_results": len(results)},
    )
    _output(response, args.format)


def cmd_naver(args: argparse.Namespace) -> None:
    """Naver 오픈 API 검색."""
    results = _search_naver(args.query, max_results=args.limit, search_type=args.type)
    if not results:
        client_id = os.environ.get("NAVER_CLIENT_ID", "")
        if not client_id:
            print(json.dumps({
                "error": "NAVER_CLIENT_ID/NAVER_CLIENT_SECRET 환경변수가 필요합니다.",
                "help": "https://developers.naver.com/ → 애플리케이션 등록 → 검색 API",
            }, ensure_ascii=False, indent=2))
            return

    response = SearchResponse(
        query=args.query,
        timestamp=_now_iso(),
        results=tuple(results),
        metadata={"backends_used": ["naver"], "total_results": len(results)},
    )
    _output(response, args.format)


def cmd_google(args: argparse.Namespace) -> None:
    """Google 검색 (차단 위험 있음)."""
    results = _search_google(args.query, max_results=args.limit, delay=args.delay)
    response = SearchResponse(
        query=args.query,
        timestamp=_now_iso(),
        results=tuple(results),
        metadata={
            "backends_used": ["google"],
            "total_results": len(results),
            "warning": "Google may block after 10-15 queries. Use --delay to mitigate.",
        },
    )
    _output(response, args.format)


def cmd_github(args: argparse.Namespace) -> None:
    """GitHub 검색 (gh CLI)."""
    results = _search_github(args.query, max_results=args.limit, search_type=args.type)
    response = SearchResponse(
        query=args.query,
        timestamp=_now_iso(),
        results=tuple(results),
        metadata={"backends_used": ["github"], "total_results": len(results)},
    )
    _output(response, args.format)


def cmd_backends(args: argparse.Namespace) -> None:
    """설치된 백엔드 상태 진단."""
    checks = {
        "ddg": _check_ddg,
        "naver": _check_naver,
        "google": _check_google,
        "wiki": _check_wiki,
        "hn": _check_hn,
        "reddit": _check_reddit,
        "feed": _check_feed,
        "github": _check_github,
    }
    statuses = {}
    for name, check_fn in checks.items():
        ok, msg = check_fn()
        statuses[name] = {"available": ok, "message": msg}

    available = sum(1 for s in statuses.values() if s["available"])
    total = len(statuses)

    print(json.dumps({
        "backends": statuses,
        "summary": f"{available}/{total} backends available",
    }, ensure_ascii=False, indent=2))


# ── Backend Health Checks ─────────────────────────────────────

def _check_ddg() -> tuple[bool, str]:
    try:
        from duckduckgo_search import DDGS
        return True, "duckduckgo-search installed"
    except ImportError:
        return False, "pip install duckduckgo-search"


def _check_naver() -> tuple[bool, str]:
    cid = os.environ.get("NAVER_CLIENT_ID", "")
    cse = os.environ.get("NAVER_CLIENT_SECRET", "")
    if cid and cse:
        return True, f"API keys configured (ID: {cid[:4]}...)"
    return False, "Set NAVER_CLIENT_ID and NAVER_CLIENT_SECRET env vars"


def _check_google() -> tuple[bool, str]:
    try:
        from googlesearch import search
        return True, "googlesearch-python installed (block risk)"
    except ImportError:
        return False, "pip install googlesearch-python"


def _check_wiki() -> tuple[bool, str]:
    try:
        import wikipedia
        return True, "wikipedia installed"
    except ImportError:
        return False, "pip install wikipedia"


def _check_hn() -> tuple[bool, str]:
    return True, "stdlib only (hn.algolia.com)"


def _check_reddit() -> tuple[bool, str]:
    return True, "stdlib only (reddit .json)"


def _check_feed() -> tuple[bool, str]:
    try:
        import feedparser
        return True, "feedparser installed"
    except ImportError:
        return False, "pip install feedparser"


def _check_github() -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0:
            return True, "gh CLI authenticated"
        return False, "gh auth login required"
    except FileNotFoundError:
        return False, "gh CLI not installed"
    except subprocess.TimeoutExpired:
        return False, "gh CLI timeout"


# ── Helpers ───────────────────────────────────────────────────

def _parse_since(since_str: str) -> int:
    """'24h', '7d', '1w' → hours."""
    since_str = since_str.strip().lower()
    if since_str.endswith("h"):
        return int(since_str[:-1])
    if since_str.endswith("d"):
        return int(since_str[:-1]) * 24
    if since_str.endswith("w"):
        return int(since_str[:-1]) * 24 * 7
    return 24


# ── Main: argparse + dispatch ─────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="web-search.py",
        description="Multi-backend Web Search CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # search
    p_search = subparsers.add_parser("search", help="Multi-backend search")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--backend", default="ddg", help="Comma-separated backends (default: ddg)")
    p_search.add_argument("--max-results", type=int, default=10, help="Max results per backend")
    p_search.add_argument("--fetch-content", action="store_true", help="Fetch content for all results")
    p_search.add_argument("--fetch-top", type=int, default=0, help="Fetch content for top N results")
    p_search.add_argument("--max-chars", type=int, default=5000, help="Max chars per fetched page")
    p_search.add_argument("--format", choices=["json", "markdown", "jsonl"], default="json")
    p_search.set_defaults(func=cmd_search)

    # fetch
    p_fetch = subparsers.add_parser("fetch", help="Fetch and extract content from URL")
    p_fetch.add_argument("url", help="URL to fetch")
    p_fetch.add_argument("--max-chars", type=int, default=5000, help="Max chars to extract")
    p_fetch.add_argument("--format", choices=["json", "markdown", "text"], default="json")
    p_fetch.set_defaults(func=cmd_fetch)

    # fetch-batch
    p_fb = subparsers.add_parser("fetch-batch", help="Fetch multiple URLs")
    p_fb.add_argument("urls", nargs="+", help="URLs to fetch")
    p_fb.add_argument("--max-chars", type=int, default=3000, help="Max chars per page")
    p_fb.add_argument("--format", choices=["json", "markdown", "jsonl"], default="json")
    p_fb.set_defaults(func=cmd_fetch_batch)

    # feed
    p_feed = subparsers.add_parser("feed", help="Parse RSS/Atom feed")
    p_feed.add_argument("feed_url", help="Feed URL")
    p_feed.add_argument("--since", default="24h", help="Filter entries since (e.g. 24h, 7d)")
    p_feed.add_argument("--max-results", type=int, default=20)
    p_feed.add_argument("--format", choices=["json", "markdown", "jsonl"], default="json")
    p_feed.set_defaults(func=cmd_feed)

    # hn
    p_hn = subparsers.add_parser("hn", help="Search HackerNews")
    p_hn.add_argument("query", help="Search query")
    p_hn.add_argument("--limit", type=int, default=10)
    p_hn.add_argument("--sort", choices=["relevance", "date", "points"], default="relevance")
    p_hn.add_argument("--format", choices=["json", "markdown", "jsonl"], default="json")
    p_hn.set_defaults(func=cmd_hn)

    # reddit
    p_reddit = subparsers.add_parser("reddit", help="Search Reddit")
    p_reddit.add_argument("query", help="Search query")
    p_reddit.add_argument("--subreddit", default="all")
    p_reddit.add_argument("--limit", type=int, default=10)
    p_reddit.add_argument("--sort", choices=["relevance", "top"], default="relevance")
    p_reddit.add_argument("--format", choices=["json", "markdown", "jsonl"], default="json")
    p_reddit.set_defaults(func=cmd_reddit)

    # naver
    p_naver = subparsers.add_parser("naver", help="Search via Naver Open API")
    p_naver.add_argument("query", help="Search query")
    p_naver.add_argument("--type", choices=["web", "blog", "news", "image"], default="web")
    p_naver.add_argument("--limit", type=int, default=10)
    p_naver.add_argument("--format", choices=["json", "markdown", "jsonl"], default="json")
    p_naver.set_defaults(func=cmd_naver)

    # google
    p_google = subparsers.add_parser("google", help="Search via Google (block risk)")
    p_google.add_argument("query", help="Search query")
    p_google.add_argument("--limit", type=int, default=10)
    p_google.add_argument("--delay", type=float, default=5.0, help="Delay between requests (sec)")
    p_google.add_argument("--format", choices=["json", "markdown", "jsonl"], default="json")
    p_google.set_defaults(func=cmd_google)

    # github
    p_github = subparsers.add_parser("github", help="Search GitHub (gh CLI)")
    p_github.add_argument("query", help="Search query")
    p_github.add_argument("--type", choices=["repos", "code", "issues"], default="repos")
    p_github.add_argument("--limit", type=int, default=10)
    p_github.add_argument("--format", choices=["json", "markdown", "jsonl"], default="json")
    p_github.set_defaults(func=cmd_github)

    # backends
    p_backends = subparsers.add_parser("backends", help="Check backend availability")
    p_backends.set_defaults(func=cmd_backends)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
