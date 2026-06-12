"""
Gemini-powered research module for BlogMaker.

Uses Google Gemini with web-grounded search to research topics
and extract citations from grounding metadata.

Three-layer research strategy:
  1. Primary search    — formal publications, vendor docs, analyst reports
  2. Practitioner search — YouTube talks, Substack, podcasts, named experts
  3. Fallback search   — fires only if grounding returns fewer than 3 sources
"""

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
        Research a topic using a three-layer strategy:

        Layer 1 — Primary search (always runs):
            Formal publications, vendor docs, analyst reports, academic papers.

        Layer 2 — Practitioner search (config-driven, keyword-gated):
            YouTube talks, Substack essays, podcast coverage, named expert
            commentary. Only fires when the topic matches keywords defined
            in config.yaml under `practitioner_topic_keywords`, AND
            `practitioner_layer_enabled` is true.

        Layer 3 — Fallback search (runs only if total sources < 3):
            Targets known authoritative domains directly when grounding
            did not activate properly.
        """
        # --- Layer 1: Primary ---
        prompt = self._build_research_prompt(topic)
        research_text, sources = self._execute_search(prompt, topic)
        logger.info("Primary search returned %d sources", len(sources))

        # --- Layer 2: Practitioner (config-driven) ---
        if self._topic_needs_practitioner_layer(topic):
            logger.info(
                "Topic '%s' flagged for practitioner layer — "
                "running expert/video search...",
                topic,
            )
            practitioner_text, practitioner_sources = self._practitioner_search(topic)
            if practitioner_text:
                research_text += (
                    "\n\n--- Practitioner & Expert Perspectives ---\n\n"
                    + practitioner_text
                )
            seen = {s.url for s in sources}
            added = 0
            for s in practitioner_sources:
                if s.url not in seen:
                    seen.add(s.url)
                    sources.append(s)
                    added += 1
            logger.info(
                "Practitioner search added %d new sources (%d total)",
                added, len(sources),
            )
        else:
            logger.info(
                "Practitioner layer skipped for '%s' "
                "(no matching keywords or layer disabled)",
                topic,
            )

        # --- Layer 3: Fallback ---
        if len(sources) < 3:
            logger.info(
                "Fewer than 3 sources total — issuing targeted fallback search..."
            )
            fallback_text, fallback_sources = self._targeted_search(topic)
            if fallback_text:
                research_text += (
                    "\n\n--- Additional Sources ---\n\n" + fallback_text
                )
            seen = {s.url for s in sources}
            for s in fallback_sources:
                if s.url not in seen:
                    seen.add(s.url)
                    sources.append(s)
            logger.info("After fallback: %d total sources", len(sources))

        return research_text, sources

    # ------------------------------------------------------------------
    # Practitioner layer gating — reads from config, no hardcoding
    # ------------------------------------------------------------------

    def _topic_needs_practitioner_layer(self, topic: str) -> bool:
        """
        Return True if the topic should trigger the practitioner layer.

        Both conditions must be true:
          1. practitioner_layer_enabled is true in config.yaml
          2. The topic contains at least one keyword from
             practitioner_topic_keywords in config.yaml

        All keywords and the on/off toggle are config-driven —
        no code change needed to adjust which topics trigger Layer 2.
        """
        if not self.config.practitioner_layer_enabled:
            return False
        topic_lower = topic.lower()
        keywords = set(self.config.practitioner_topic_keywords)
        return any(kw in topic_lower for kw in keywords)

    # ------------------------------------------------------------------
    # Search execution
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
                logger.info(
                    "Researching '%s' (attempt %d/%d)...",
                    topic, attempt, self.config.max_retries,
                )
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=research_config,
                )
                self._track_tokens(response)

                research_text = response.text or ""
                sources = self._extract_sources(response)
                logger.info(
                    "Search complete — %d words, %d sources",
                    len(research_text.split()), len(sources),
                )
                return research_text, sources

            except Exception as e:
                last_error = e
                logger.warning(
                    "Gemini API error (attempt %d/%d): %s",
                    attempt, self.config.max_retries, str(e),
                )
                if attempt < self.config.max_retries:
                    delay = self.config.retry_delay_seconds * (2 ** (attempt - 1))
                    logger.info("Retrying in %d seconds...", delay)
                    time.sleep(delay)

        raise RuntimeError(
            f"Gemini research failed after {self.config.max_retries} attempts. "
            f"Last error: {last_error}"
        )

    # ------------------------------------------------------------------
    # Layer 2 — Practitioner search
    # ------------------------------------------------------------------

    def _practitioner_search(self, topic: str) -> tuple[str, list[Source]]:
        """
        Search for practitioner voices: YouTube talks, Substack essays,
        podcast coverage, and commentary from named experts in AI/tech.

        This layer captures opinion and nuance that formal publications miss —
        e.g. Andrej Karpathy on automation, Geoffrey Hinton on job displacement,
        engineers writing on Substack about what they actually observe.
        """
        prompt = f"""Find practitioner perspectives, expert commentary, and \
video/podcast content on: "{topic}"

Search specifically for:
- YouTube talks and lectures from credible AI/tech researchers and engineers
  (e.g. Andrej Karpathy, Yann LeCun, Geoffrey Hinton, Demis Hassabis, Sam Altman,
  Fei-Fei Li, Andrew Ng — or whoever is most relevant to this specific topic)
- Podcast episodes with substantive expert discussion (Lex Fridman Podcast,
  No Priors, 80,000 Hours, Hard Fork, AI Breakdown, Bankless — relevant ones only)
- Substack essays and newsletters from respected practitioners and researchers
  (Import AI by Jack Clark, The Batch by Andrew Ng, Stratechery, Matt Levine
  where relevant — whoever actually covers this topic)
- Long-form interviews in MIT Technology Review, Wired, or The Atlantic where
  researchers speak in their own words
- Informed opinion pieces and essays from engineers or researchers with direct
  first-hand experience of this topic

For each source:
- State who the person is and why their perspective is credible
- Summarise their core argument or observation
- Note if multiple credible voices agree or disagree on a key point
- Include the URL if you can ground it

Skip: anonymous blogs, engagement-bait opinion pieces, content from people with
no direct expertise in the topic."""

        try:
            text, sources = self._execute_search(
                prompt, f"{topic} (practitioner layer)"
            )
            return text, sources
        except Exception as e:
            logger.warning("Practitioner search failed: %s", str(e))
            return "", []

    # ------------------------------------------------------------------
    # Layer 3 — Targeted fallback
    # ------------------------------------------------------------------

    def _targeted_search(self, topic: str) -> tuple[str, list[Source]]:
        """
        Fallback search targeting known authoritative domains directly.
        Only runs when grounding returned fewer than 3 sources total,
        indicating grounding did not activate properly.
        """
        prompt = f"""Find authoritative, original-source articles on: "{topic}"

Search specifically for:
- Official vendor documentation and engineering blogs:
  Microsoft (learn.microsoft.com, techcommunity.microsoft.com),
  SAP (news.sap.com, community.sap.com, help.sap.com),
  Google Cloud Blog, AWS Machine Learning Blog, Salesforce Engineering,
  ServiceNow Blog, Anthropic, OpenAI, NVIDIA Technical Blog
- Analyst firms: Gartner, Forrester, IDC (press releases and summaries are fine)
- Peer-reviewed and technical publications: IEEE Xplore, ACM Digital Library, arXiv
- Enterprise tech journalism: InfoQ, The Register, ZDNet, Ars Technica,
  VentureBeat, TechCrunch Enterprise, Computerworld, CIO.com
- SAP ecosystem: SAP News Center, ASUG (asug.com), SAPinsider

Return key findings and concrete data points from these sources only.
Skip aggregators, listicles, and SEO-farm content."""

        try:
            text, sources = self._execute_search(prompt, f"{topic} (fallback)")
            return text, sources
        except Exception as e:
            logger.warning("Targeted fallback search failed: %s", str(e))
            return "", []

    # ------------------------------------------------------------------
    # Prompts
    # ------------------------------------------------------------------

    def _build_research_prompt(self, topic: str) -> str:
        return f"""You are a senior technology research analyst covering enterprise \
software, AI, and digital transformation.

TOPIC (use exactly as written — do NOT reinterpret or modify):
"{topic}"

RESEARCH INSTRUCTIONS:
1. Search for the most recent, technically accurate information on this topic.

2. STRONGLY prioritize authoritative, original sources. For this domain:
   - Official vendor sources:
     Microsoft (learn.microsoft.com, techcommunity.microsoft.com),
     SAP (news.sap.com, community.sap.com, help.sap.com),
     Google Cloud Blog, AWS Blog, Salesforce, ServiceNow, Anthropic, OpenAI, NVIDIA
   - Analyst firms: Gartner, Forrester, IDC
   - Technical publications: IEEE Xplore, ACM Digital Library, arXiv (cs.AI, cs.SE, cs.IR)
   - Enterprise tech journalism: InfoQ, The Register, ZDNet, Ars Technica,
     VentureBeat, TechCrunch, Computerworld, CIO.com
   - SAP ecosystem: ASUG (asug.com), SAPinsider, SAP News Center
   - Do NOT rely on generic SEO content farms, listicle blogs, or unsourced aggregators

3. Prioritize technical depth over breadth:
   - Concrete specs, version numbers, release dates, and API/SDK names
   - Benchmark figures and performance data where available
   - Real enterprise deployment examples and case studies
   - Vendor claims clearly separated from independent analyst assessments

4. Include:
   - Specific data points, statistics, and official release notes
   - Expert and analyst quotes with attribution
   - Adoption challenges and enterprise integration considerations
   - Known limitations, open issues, and areas of active development
   - Recent announcements (within the last 12 months where possible)

5. Cite every factual claim with its source so it can be verified.

Provide a comprehensive research summary of approximately \
{self.config.article_words} words with specific technical facts \
and recent developments."""

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
            logger.warning("No candidates in response")
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

                        # Resolve Google grounding redirect URLs to real destination
                        if (
                            "google.com/url" in url
                            or "vertexaisearch.cloud.google.com" in url
                        ):
                            try:
                                r = requests.head(
                                    url, allow_redirects=True, timeout=5
                                )
                                url = r.url
                            except Exception as e:
                                logger.debug(
                                    "Failed to resolve redirect %s: %s", url, e
                                )

                        # Extract publisher from "Title - Publisher" or "Title | Publisher"
                        publisher = ""
                        if " - " in title:
                            publisher = title.split(" - ")[-1].strip()
                        elif " | " in title:
                            publisher = title.split(" | ")[-1].strip()

                        sources.append(
                            Source(url=url, title=title, publisher=publisher)
                        )

        logger.info("Extracted %d unique sources", len(sources))
        return sources

    # ------------------------------------------------------------------
    # Token tracking
    # ------------------------------------------------------------------

    def _track_tokens(self, response: types.GenerateContentResponse) -> None:
        """Accumulate token usage for cost tracking."""
        if not self.config.enable_cost_tracking:
            return
        try:
            usage = response.usage_metadata
            if usage:
                self._total_input_tokens += (
                    getattr(usage, "prompt_token_count", 0) or 0
                )
                self._total_output_tokens += (
                    getattr(usage, "candidates_token_count", 0) or 0
                )
        except Exception:
            pass