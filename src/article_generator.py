"""
Article generator for BlogMaker.

Takes research output and produces a structured Article using Gemini.
Enforces article length and structural validation before accepting output.
Tuned for a senior enterprise software engineer writing LinkedIn posts
on SAP, Copilot, AI-in-enterprise, and broader AI/society topics.
"""

import json
import re
import time

from google import genai
from google.genai import types

from src.config import AppConfig
from src.logger import get_logger
from src.models import Article, Source

logger = get_logger("article_generator")

MAX_EXPANSION_ATTEMPTS = 2


class ArticleGenerator:
    """Generates structured newsletter articles from research data."""

    def __init__(self, config: AppConfig, client: genai.Client | None = None) -> None:
        self.config = config
        self.client = client or genai.Client(api_key=config.gemini_api_key)
        self.model = config.gemini_model
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        logger.info("Article generator initialized")

    @property
    def input_tokens(self) -> int:
        return self._total_input_tokens

    @property
    def output_tokens(self) -> int:
        return self._total_output_tokens

    def generate_article(
        self,
        topic: str,
        research_text: str,
        sources: list[Source],
    ) -> Article:
        """
        Generate a structured newsletter article with length enforcement.

        If the generated article is below 90% of the target word count,
        an expansion prompt is issued automatically (up to 2 attempts).
        """
        prompt = self._build_article_prompt(topic, research_text, sources)
        gen_config = types.GenerateContentConfig(
            temperature=0.5,
            response_mime_type="application/json",
        )

        last_error: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                logger.info(
                    "Generating article for '%s' (attempt %d/%d)...",
                    topic, attempt, self.config.max_retries,
                )
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=gen_config,
                )
                self._track_tokens(response)

                raw_text = response.text or ""
                article = self._parse_response(topic, raw_text, sources)

                # Structural validation — retry on this attempt if fixable
                validation_issues = self._validate_structure(article)
                if validation_issues:
                    logger.warning(
                        "Article structure issues: %s", "; ".join(validation_issues)
                    )
                    if attempt < self.config.max_retries:
                        logger.info("Regenerating due to structural issues...")
                        continue

                # Length enforcement — expansion happens after structural pass
                article = self._enforce_length(article, topic, research_text, sources)

                word_count = len(article.main_content.split())
                logger.info(
                    "Article accepted — title: '%s', %d words "
                    "(target: %d, range: %d–%d)",
                    article.title, word_count, self.config.article_words,
                    int(self.config.article_words * 0.9),
                    int(self.config.article_words * 1.1),
                )
                return article

            except Exception as e:
                last_error = e
                logger.warning(
                    "Article generation error (attempt %d/%d): %s",
                    attempt, self.config.max_retries, str(e),
                )
                if attempt < self.config.max_retries:
                    delay = self.config.retry_delay_seconds * (2 ** (attempt - 1))
                    time.sleep(delay)

        raise RuntimeError(
            f"Article generation failed after {self.config.max_retries} attempts. "
            f"Last error: {last_error}"
        )

    # ------------------------------------------------------------------
    # Validation & length enforcement
    # ------------------------------------------------------------------

    def _validate_structure(self, article: Article) -> list[str]:
        """Validate all required sections meet minimum content requirements."""
        issues: list[str] = []
        if len(article.takeaways) < self.config.key_takeaways:
            issues.append(
                f"takeaways: got {len(article.takeaways)}, "
                f"need {self.config.key_takeaways}"
            )
        if len(article.key_concepts) < self.config.key_concepts_count:
            issues.append(
                f"key_concepts: got {len(article.key_concepts)}, "
                f"need {self.config.key_concepts_count}"
            )
        if len(article.linkedin_ideas) < self.config.linkedin_angles:
            issues.append(
                f"linkedin_ideas: got {len(article.linkedin_ideas)}, "
                f"need {self.config.linkedin_angles}"
            )
        if not article.executive_summary:
            issues.append("executive_summary is empty")
        if not article.main_content:
            issues.append("main_content is empty")
        if not article.title:
            issues.append("title is empty")
        return issues

    def _enforce_length(
        self,
        article: Article,
        topic: str,
        research_text: str,
        sources: list[Source],
    ) -> Article:
        """Enforce article length within 10% tolerance of the configured target."""
        target = self.config.article_words
        min_words = int(target * 0.9)
        actual = len(article.main_content.split())

        logger.info(
            "Length check: target=%d, actual=%d, min=%d", target, actual, min_words
        )

        if actual >= min_words:
            return article

        for exp_attempt in range(1, MAX_EXPANSION_ATTEMPTS + 1):
            logger.warning(
                "Article too short (%d words, minimum %d). "
                "Expanding (attempt %d/%d)...",
                actual, min_words, exp_attempt, MAX_EXPANSION_ATTEMPTS,
            )
            article = self._expand_article(article, target, actual)
            actual = len(article.main_content.split())
            logger.info("After expansion: %d words", actual)
            if actual >= min_words:
                return article

        logger.warning(
            "Article still short after %d expansions (%d words vs %d target). "
            "Accepting as-is.",
            MAX_EXPANSION_ATTEMPTS, actual, target,
        )
        return article

    def _expand_article(self, article: Article, target: int, current: int) -> Article:
        """Issue an expansion prompt to bring an undersized article up to target length."""
        deficit = target - current
        expand_prompt = f"""The following article is too short.
Current: {current} words. Target: {target} words (minimum {int(target * 0.9)}).

Add approximately {deficit} more words. Expand with:
- Deeper technical analysis and architectural trade-offs
- Vendor-specific implementation details, version numbers, or SDK specifics
- Real-world deployment examples or enterprise case studies
- Independent analyst or practitioner perspective where it differs from vendor claims
- Named expert viewpoints if the topic has a practitioner/opinion dimension

Do NOT add filler, repetition, or generic observations.

CURRENT ARTICLE:
{article.main_content}

Return ONLY the expanded article body text. No JSON wrapper, no extra section headers."""

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=expand_prompt,
                config=types.GenerateContentConfig(temperature=0.5),
            )
            self._track_tokens(response)
            expanded = response.text or ""
            if len(expanded.split()) > len(article.main_content.split()):
                article.main_content = expanded
        except Exception as e:
            logger.warning("Expansion attempt failed: %s", str(e))

        return article

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_article_prompt(
        self,
        topic: str,
        research_text: str,
        sources: list[Source],
    ) -> str:
        """Build the structured article generation prompt."""
        source_list = "\n".join(
            f"- [{s.title}]({s.url})" for s in sources if s.url
        ) or "No specific sources available."

        return f"""You are writing a daily research brief for a senior software engineer \
(25+ years of enterprise experience) who reads it each morning and then writes \
their own LinkedIn post based on it.

TOPIC (use EXACTLY as written — do NOT reinterpret, broaden, or narrow):
"{topic}"

RESEARCH DATA:
{research_text}

AVAILABLE SOURCES:
{source_list}

READER PROFILE:
- Senior software engineer / solutions architect, ~50 years old
- Deep background in SAP ecosystems, enterprise ERP, and systems integration
- Current interest areas: AI in enterprise software, Microsoft Copilot, SAP AI
  capabilities, practical AI deployment, digital transformation at scale,
  and broader AI/society questions (job displacement, regulation, ethics)
- Purpose of this brief: they will read it, form their own view, and write a
  LinkedIn post — give them real substance to react to, not a sanitised summary
- Tone they respond to: technically honest, peer-to-peer, vendor claims clearly
  labelled as such, real trade-offs surfaced, no hype

INSTRUCTIONS:
Write a structured newsletter article. Return valid JSON.

CRITICAL LENGTH REQUIREMENTS:
- main_content: EXACTLY ~{self.config.article_words} words \
(minimum {int(self.config.article_words * 0.9)})
- executive_summary: ~{self.config.executive_summary_words} words
- key_concepts: EXACTLY {self.config.key_concepts_count} items \
(each a technically precise paragraph)
- counterpoints: EXACTLY {self.config.counterpoints} items \
(real criticism, not strawmen)
- takeaways: EXACTLY {self.config.key_takeaways} bullet points
- linkedin_ideas: EXACTLY {self.config.linkedin_angles} angles
- topic_refinement: 2–3 sentences suggesting a more specific angle worth exploring next
- career_implications: populate ONLY when directly relevant to enterprise tech roles; \
leave as empty string otherwise

WRITING STYLE:
- Tone: Direct, analytically credible, peer-to-peer — write for someone who will
  fact-check you
- Do NOT use: "game-changer", "revolutionary", "transformative", "unlock potential",
  "in today's fast-paced world", or any enterprise buzzwords — this reader will stop
  reading the moment they see one
- Clearly distinguish:
    (a) vendor marketing claims
    (b) independent analyst findings (Gartner, Forrester, IDC, academic papers)
    (c) practitioner and expert opinion (named researchers, engineers, YouTube talks,
        podcast commentary)
    (d) real-world deployment reports and case studies
- For technical topics: include specific product names, version numbers, release dates,
  and API/SDK names — e.g. "Copilot for Microsoft 365", "SAP S/4HANA 2023 FPS02",
  not vague references like "Microsoft's AI tools"
- For opinion/society topics: represent named expert voices faithfully, note where
  credible people disagree, and avoid collapsing nuanced positions into a single view
- Acknowledge known limitations, open questions, and where evidence is genuinely thin

RESEARCH DATA NOTE:
The RESEARCH DATA above may contain multiple sections — a primary research section,
a "Practitioner & Expert Perspectives" section, and/or an "Additional Sources" section.
Treat all of them as a single unified source pool. Do NOT reference or expose this
section structure in the article itself. Weave formal sources and practitioner voices
together naturally.

CITATIONS:
- Use inline citations [1], [2] throughout main_content referencing the provided sources
- YouTube videos, podcast episodes, and Substack posts are valid citations — treat them
  the same as articles
- End main_content with a '### References' section mapping each number to the exact
  source title from AVAILABLE SOURCES

LINKEDIN IDEAS:
Each linkedin_idea must be a concrete angle a senior enterprise practitioner would
genuinely post about — grounded in a specific observation, data point, or honest opinion.

  Good example: "What Karpathy's 'Software 2.0' framing actually means for how we
  staff and skill SAP integration teams — and why most companies are getting this wrong"

  Bad example: "AI is transforming enterprise software — here's what you need to know 🚀"

Return a JSON object with these exact keys:
{{
    "title": "string",
    "executive_summary": "string (~{self.config.executive_summary_words} words)",
    "main_content": "string (markdown, ~{self.config.article_words} words, \
inline citations)",
    "key_concepts": ["string", ...],
    "industry_impact": "string",
    "career_implications": "string",
    "counterpoints": ["string", ...],
    "takeaways": ["string", ...],
    "linkedin_ideas": ["string", ...],
    "topic_refinement": "string"
}}"""

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_response(
        self,
        topic: str,
        raw_text: str,
        sources: list[Source],
    ) -> Article:
        """Parse the JSON response into an Article dataclass."""
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw_text)
            if json_match:
                try:
                    data = json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    logger.warning(
                        "Failed to parse extracted JSON block, using fallback"
                    )
                    data = {
                        "main_content": raw_text,
                        "title": f"Research Brief: {topic}",
                    }
            else:
                logger.warning("No JSON found in response, using fallback")
                data = {
                    "main_content": raw_text,
                    "title": f"Research Brief: {topic}",
                }

        return Article(
            topic=topic,
            title=data.get("title", f"Research Brief: {topic}"),
            executive_summary=data.get("executive_summary", ""),
            main_content=data.get("main_content", ""),
            key_concepts=self._ensure_list(data.get("key_concepts", [])),
            industry_impact=data.get("industry_impact", ""),
            career_implications=data.get("career_implications", ""),
            counterpoints=self._ensure_list(data.get("counterpoints", [])),
            takeaways=self._ensure_list(data.get("takeaways", [])),
            linkedin_ideas=self._ensure_list(data.get("linkedin_ideas", [])),
            topic_refinement=data.get("topic_refinement", ""),
            sources=sources,
        )

    @staticmethod
    def _ensure_list(value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value]
        if isinstance(value, str):
            return [value]
        return []

    # ------------------------------------------------------------------
    # Token tracking
    # ------------------------------------------------------------------

    def _track_tokens(self, response: types.GenerateContentResponse) -> None:
        """Accumulate token usage from API response for cost tracking."""
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