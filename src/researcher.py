"""
Gemini-powered research module for BlogMaker.

Uses Google Gemini with web-grounded search to research topics
and extract citations from grounding metadata.

Research strategy:
  1. Query decomposition — Gemini breaks the topic into focused sub-queries
  2. Fan-out search      — each sub-query runs as a separate grounded search
  3. Practitioner search — config-driven; fires for opinion/society topics
  4. Merge & deduplicate — all results combined into one research pool
"""

import json
import time
import requests

from google import genai
from google.genai import types

from src.config import AppConfig
from src.logger import get_logger
from src.models import Source

logger = get_logger("researcher")


class GeminiResearcher:
    """Researches topics using Gemini with grounded web search."""

    def __init__(self, config: AppConfig, client: genai.Client | None = None) -> None:
        self.config = config
        self.client = client or genai.Client(api_key=config.gemini_api_key)
        self.model = config.gemini_model
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        logger.info("Gemini researcher initialized (model: %s)", self.model)

    @property
    def input_tokens(self) -> int:
        return self._total_input_tokens

    @property
    def output_tokens(self) -> int:
        return self._total_output_tokens

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def research_topic(self, topic: str) -> tuple[str, list[Source]]:
        """
        Research a topic using fan-out search.

        Step 1: Ask Gemini to decompose the topic into focused sub-queries.
        Step 2: Run each sub-query as a separate grounded search.
        Step 3: Optionally run practitioner search (config-driven).
        Step 4: Merge all text and deduplicate all sources.
        Step 5: Synthesise into a single coherent research summary.
        """
        # --- Step 1: Decompose topic into sub-queries ---
        sub_queries = self._decompose_topic(topic)
        logger.info("Topic decomposed into %d sub-queries: %s", len(sub_queries), sub_queries)

        # --- Step 2: Fan-out — run each sub-query separately ---
        all_texts: list[str] = []
        all_sources: list[Source] = []
        seen_urls: set[str] = set()

        for i, query in enumerate(sub_queries, 1):
            logger.info("Running sub-query %d/%d: '%s'", i, len(sub_queries), query)
            try:
                text, sources = self._execute_search(
                    self._build_subquery_prompt(query, topic), query
                )
                if text:
                    all_texts.append(f"### Sub-query: {query}\n\n{text}")
                for s in sources:
                    if s.url and s.url not in seen_urls:
                        seen_urls.add(s.url)
                        all_sources.append(s)
            except Exception as e:
                logger.warning("Sub-query '%s' failed: %s", query, str(e))
                continue

        logger.info(
            "Fan-out complete — %d sub-queries, %d unique sources",
            len(sub_queries), len(all_sources),
        )

        # --- Step 3: Practitioner layer (config-driven) ---
        if self._topic_needs_practitioner_layer(topic):
            logger.info("Running practitioner layer for '%s'...", topic)
            practitioner_text, practitioner_sources = self._practitioner_search(topic)
            if practitioner_text:
                all_texts.append(
                    "### Practitioner & Expert Perspectives\n\n" + practitioner_text
                )
            for s in practitioner_sources:
                if s.url and s.url not in seen_urls:
                    seen_urls.add(s.url)
                    all_sources.append(s)
            logger.info("After practitioner layer: %d total sources", len(all_sources))

        # --- Step 4: Synthesise all research into one summary ---
        combined_raw = "\n\n---\n\n".join(all_texts)
        research_text = self._synthesise(topic, combined_raw, all_sources)

        logger.info(
            "Research complete — %d words, %d sources",
            len(research_text.split()), len(all_sources),
        )
        return research_text, all_sources

    # ------------------------------------------------------------------
    # Step 1: Topic decomposition
    # ------------------------------------------------------------------

    def _decompose_topic(self, topic: str) -> list[str]:
        """
        Ask Gemini to break the topic into 4-6 focused search sub-queries.
        Each sub-query will be run as a separate grounded search, just like
        Perplexity decomposes questions before searching.
        """
        decompose_prompt = f"""You are a research planner. Break the following topic into focused search queries.

TOPIC: "{topic}"

Generate 4-6 search queries that together give comprehensive coverage of this topic.
Rules:
- Each query should target a distinct angle or sub-theme
- Each query should be specific enough to return authoritative sources
  (analyst reports, vendor docs, academic papers, or tier-1 tech journalism)
- Do NOT overlap — each query should find different information
- If the topic is broad (e.g. "Cybersecurity Trends"), generate queries covering
  different themes within it
- If the topic is specific (e.g. "SAP Joule vs Microsoft Copilot"), generate
  queries covering different dimensions of that specific subject

Return ONLY a JSON array of strings. No explanation, no markdown, just the array.
Example format: ["query one", "query two", "query three"]"""

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=decompose_prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    response_mime_type="application/json",
                ),
            )
            self._track_tokens(response)
            raw = response.text or "[]"
            queries = json.loads(raw)
            if isinstance(queries, list) and len(queries) >= 2:
                return [str(q) for q in queries[:6]]  # Cap at 6
        except Exception as e:
            logger.warning("Topic decomposition failed: %s — falling back to single search", str(e))

        # Fallback: use topic as a single query
        return [topic]

    # ------------------------------------------------------------------
    # Step 2: Sub-query search prompt
    # ------------------------------------------------------------------

    def _build_subquery_prompt(self, query: str, original_topic: str) -> str:
        """
        Build a focused prompt for a single sub-query search.
        Keeps source quality guidance without biasing the angle.
        """
        return f"""You are a senior research analyst.

Search for and summarise the most authoritative, recent information on:
"{query}"

Context: this is part of broader research on "{original_topic}"

SOURCE QUALITY — prioritise in this order:
1. Analyst research: Gartner, Forrester, IDC, McKinsey, Deloitte Insights
2. Peer-reviewed: arXiv, IEEE Xplore, ACM Digital Library, MIT Technology Review
3. Government / standards bodies: NIST, CISA, ENISA and relevant regulators
4. Authoritative tech journalism: Ars Technica, The Register, InfoQ, ZDNet,
   VentureBeat, TechCrunch, Computerworld, CIO.com
5. Official vendor technical documentation, engineering blogs, threat intelligence
   reports (not marketing pages)

DO NOT cite: career blogs, university course pages, vendor marketing landing pages,
listicle SEO articles, or sources whose primary purpose is lead generation.

Return:
- Key findings with specific data, statistics, and named expert quotes
- Source attributions for every factual claim
- Approximately 300-400 words"""

    # ------------------------------------------------------------------
    # Step 4: Synthesis
    # ------------------------------------------------------------------

    def _synthesise(
        self, topic: str, combined_raw: str, sources: list[Source]
    ) -> str:
        """
        Take all sub-query research results and synthesise into one
        coherent, non-repetitive research summary.
        """
        if not combined_raw.strip():
            return ""

        source_list = "\n".join(
            f"- [{s.title}]({s.url})" for s in sources if s.url
        )

        synthesis_prompt = f"""You are a senior research analyst. Below are research findings
from multiple focused searches on the topic: "{topic}"

Your task: synthesise all of this into ONE coherent research summary of approximately
{self.config.article_words} words.

Rules:
- Do NOT repeat the same point from multiple sub-queries — merge and deduplicate
- Preserve all specific data points, statistics, and named expert quotes
- Maintain the breadth — if the sub-queries covered 5 different angles,
  the summary must cover all 5
- Cite sources using [1], [2] etc. referencing the source list below
- Do NOT add new information not present in the raw research below

AVAILABLE SOURCES (for citation numbering):
{source_list}

RAW RESEARCH FROM ALL SUB-QUERIES:
{combined_raw}"""

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=synthesis_prompt,
                config=types.GenerateContentConfig(temperature=0.2),
            )
            self._track_tokens(response)
            return response.text or combined_raw
        except Exception as e:
            logger.warning("Synthesis failed: %s — using raw combined text", str(e))
            return combined_raw

    # ------------------------------------------------------------------
    # Practitioner layer
    # ------------------------------------------------------------------

    def _topic_needs_practitioner_layer(self, topic: str) -> bool:
        if not self.config.practitioner_layer_enabled:
            return False
        topic_lower = topic.lower()
        keywords = set(self.config.practitioner_topic_keywords)
        return any(kw in topic_lower for kw in keywords)

    def _practitioner_search(self, topic: str) -> tuple[str, list[Source]]:
        prompt = f"""Search for practitioner perspectives and expert commentary on: "{topic}"

Find:
- YouTube talks or lectures from credible researchers and engineers
- Podcast episodes with substantive expert discussion
- Substack essays from respected practitioners
- Long-form interviews where named experts speak in their own words

For each source: who the person is, their core argument, and the URL.
Skip anonymous blogs and engagement-bait content."""

        try:
            return self._execute_search(prompt, f"{topic} (practitioner layer)")
        except Exception as e:
            logger.warning("Practitioner search failed: %s", str(e))
            return "", []

    # ------------------------------------------------------------------
    # Core search execution
    # ------------------------------------------------------------------

    def _execute_search(self, prompt: str, topic: str) -> tuple[str, list[Source]]:
        """Execute a single grounded search with exponential-backoff retries."""
        grounding_tool = types.Tool(google_search=types.GoogleSearch())
        research_config = types.GenerateContentConfig(
            tools=[grounding_tool],
            temperature=0.3,
        )

        last_error: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=research_config,
                )
                self._track_tokens(response)
                research_text = response.text or ""
                sources = self._extract_sources(response)
                return research_text, sources

            except Exception as e:
                last_error = e
                logger.warning(
                    "Gemini API error (attempt %d/%d): %s",
                    attempt, self.config.max_retries, str(e),
                )
                if attempt < self.config.max_retries:
                    delay = self.config.retry_delay_seconds * (2 ** (attempt - 1))
                    time.sleep(delay)

        raise RuntimeError(
            f"Gemini research failed after {self.config.max_retries} attempts. "
            f"Last error: {last_error}"
        )

    # ------------------------------------------------------------------
    # Source extraction
    # ------------------------------------------------------------------

    def _extract_sources(
        self, response: types.GenerateContentResponse
    ) -> list[Source]:
        """Extract source citations from Gemini grounding metadata."""
        sources: list[Source] = []
        seen_urls: set[str] = set()

        if not response.candidates:
            return sources

        candidate = response.candidates[0]
        if not candidate.grounding_metadata:
            logger.warning("No grounding metadata — model may not have searched")
            return sources

        metadata = candidate.grounding_metadata

        if metadata.web_search_queries:
            logger.info("Search queries used: %s", metadata.web_search_queries)

        if metadata.grounding_chunks:
            for chunk in metadata.grounding_chunks:
                if chunk.web:
                    url = chunk.web.uri or ""
                    title = chunk.web.title or ""

                    if url and url not in seen_urls:
                        seen_urls.add(url)

                        if (
                            "google.com/url" in url
                            or "vertexaisearch.cloud.google.com" in url
                        ):
                            try:
                                r = requests.head(url, allow_redirects=True, timeout=5)
                                url = r.url
                            except Exception as e:
                                logger.debug("Failed to resolve redirect %s: %s", url, e)

                        publisher = ""
                        if " - " in title:
                            publisher = title.split(" - ")[-1].strip()
                        elif " | " in title:
                            publisher = title.split(" | ")[-1].strip()

                        sources.append(Source(url=url, title=title, publisher=publisher))

        return sources

    # ------------------------------------------------------------------
    # Token tracking
    # ------------------------------------------------------------------

    def _track_tokens(self, response: types.GenerateContentResponse) -> None:
        if not self.config.enable_cost_tracking:
            return
        try:
            usage = response.usage_metadata
            if usage:
                self._total_input_tokens += getattr(usage, "prompt_token_count", 0) or 0
                self._total_output_tokens += getattr(usage, "candidates_token_count", 0) or 0
        except Exception:
            pass