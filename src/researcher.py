"""
Gemini-powered research module for BlogMaker.

Uses Google Gemini with web-grounded search to research topics
and extract citations from grounding metadata.

Three-layer research strategy:
  1. Primary search     — always runs; broad, faithful to the topic as given
  2. Practitioner search — config-driven; fires for opinion/society topics
  3. Fallback search    — fires only if grounding returns fewer than 3 sources
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
        Research a topic using a three-layer strategy.

        Layer 1 — Primary search (always runs):
            Searches faithfully for the topic exactly as given.
            If the topic is broad (e.g. "Cybersecurity Trends"), the search
            is kept broad — no narrowing or reframing by the model.

        Layer 2 — Practitioner search (config-driven, keyword-gated):
            YouTube talks, Substack essays, podcast coverage, named expert
            commentary. Only fires when the topic matches keywords defined
            in config.yaml under practitioner_topic_keywords AND
            practitioner_layer_enabled is true.

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
                "(no matching keywords or layer disabled in config)",
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
    # Practitioner layer gating — fully config-driven
    # ------------------------------------------------------------------

    def _topic_needs_practitioner_layer(self, topic: str) -> bool:
        """
        Return True if the topic should trigger the practitioner layer.

        Both conditions must be true:
          1. practitioner_layer_enabled is true in config.yaml
          2. The topic contains at least one keyword from
             practitioner_topic_keywords in config.yaml

        No keywords are hardcoded here — edit config.yaml to change behaviour.
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
        """
        prompt = f"""Search for practitioner perspectives and expert commentary on: "{topic}"

Find:
- YouTube talks or lectures from credible researchers and engineers relevant to this topic
- Podcast episodes with substantive expert discussion relevant to this topic
- Substack essays or newsletters from respected practitioners who cover this topic
- Long-form interviews where named experts speak in their own words
- Opinion pieces from engineers or researchers with direct first-hand experience

For each source:
- State who the person is and why their perspective is credible
- Summarise their core argument or finding
- Note where credible voices agree or disagree
- Include the URL

Skip: anonymous blogs, engagement-bait content, people with no direct expertise."""

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
        Fallback search targeting authoritative domains directly.
        Only runs when total sources < 3, indicating grounding did not
        activate properly.
        """
        prompt = f"""Find authoritative, original-source articles on: "{topic}"

Prioritise:
- Official vendor documentation and engineering blogs (Microsoft, SAP, Google Cloud,
  AWS, Salesforce, ServiceNow, Anthropic, OpenAI, NVIDIA)
- Analyst firms: Gartner, Forrester, IDC
- Peer-reviewed publications: IEEE Xplore, ACM Digital Library, arXiv
- Enterprise tech journalism: InfoQ, The Register, ZDNet, Ars Technica,
  VentureBeat, TechCrunch, Computerworld, CIO.com
- SAP ecosystem: SAP News Center, ASUG, SAPinsider

Return key findings and concrete data points. Skip aggregators and SEO content."""

        try:
            text, sources = self._execute_search(prompt, f"{topic} (fallback)")
            return text, sources
        except Exception as e:
            logger.warning("Targeted fallback search failed: %s", str(e))
            return "", []

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_research_prompt(self, topic: str) -> str:
        """
        Build the primary research prompt.

        Key design principle: the prompt must not push Gemini toward any
        particular angle. It anchors the topic firmly, then lets Gemini's
        grounding decide what the most authoritative current sources are.
        The more prescriptive the domain hints in the prompt, the more
        Gemini drifts toward those hints instead of the actual topic.
        """
        return f"""You are a senior technology research analyst.

YOUR TASK:
Research the following topic and produce a comprehensive factual summary.

TOPIC:
"{topic}"

CRITICAL INSTRUCTION — READ BEFORE SEARCHING:
Search for this topic EXACTLY as written above. Do not rename it, reframe it,
or decide that a more specific sub-angle would be more interesting.

- If the topic is BROAD (e.g. "Cybersecurity Trends", "AI in Enterprise"),
  keep the research BROAD. Cover all major themes with roughly equal depth.
  Do NOT pick the most prominent current news angle and treat it as the whole topic.

- If the topic contains the word "trends", you MUST identify and cover a minimum
  of 4-5 distinct trends. Do not collapse them into one overarching narrative.

- If the topic is SPECIFIC (e.g. "SAP Joule vs Microsoft Copilot"),
  stay tightly focused on that specific comparison or question.

- Vendor claims and independent analyst findings must be clearly separated.
  Label which is which.

WHAT TO FIND:
- Recent, technically accurate information (last 12 months where possible)
- Concrete data: statistics, version numbers, release dates, benchmark figures
- Real-world deployment examples and enterprise case studies
- Expert and analyst quotes with full attribution
- Known limitations, open questions, and areas of active debate
- Multiple perspectives — do not present only the consensus view

SOURCES:
Use whatever authoritative sources your search returns for this specific topic.
Cite every factual claim so it can be verified.

Provide a research summary of approximately {self.config.article_words} words."""

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
