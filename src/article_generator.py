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

                # Topic fidelity check — reject if title reframes the topic
                if self._title_drifted(article.title, topic):
                    logger.warning(
                        "Title drift detected: topic='%s', title='%s'. Regenerating...",
                        topic, article.title,
                    )
                    if attempt < self.config.max_retries:
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
    # Validation & fidelity checks
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

    def _title_drifted(self, title: str, topic: str) -> bool:
        """
        Return True if the generated title appears to have reframed the topic.

        Logic: at least one meaningful word from the topic must appear in the
        title. If zero topic words appear, the title has likely been reframed
        into a completely different angle and should be regenerated.

        Stop words (the, a, an, in, of, for, and, is, are, etc.) are excluded
        so they don't produce false negatives.
        """
        STOP_WORDS = {
            "the", "a", "an", "in", "of", "for", "and", "or", "is", "are",
            "to", "on", "at", "it", "its", "this", "that", "with", "by",
            "as", "be", "was", "were", "has", "have", "had", "not", "but",
            "from", "into", "will", "can", "how", "why", "what", "when",
        }
        topic_words = {
            w for w in topic.lower().split()
            if w not in STOP_WORDS and len(w) > 3
        }
        title_lower = title.lower()

        if not topic_words:
            return False  # Topic is too short to check — pass it through

        matches = sum(1 for w in topic_words if w in title_lower)
        # If fewer than half the meaningful topic words appear in the title,
        # flag as drift. For a 1-word topic any match is sufficient.
        threshold = max(1, len(topic_words) // 2)
        drifted = matches < threshold

        if drifted:
            logger.debug(
                "Title drift check: topic_words=%s, matches=%d, threshold=%d",
                topic_words, matches, threshold,
            )
        return drifted

    # ------------------------------------------------------------------
    # Length enforcement
    # ------------------------------------------------------------------

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

TOPIC — THIS IS THE SUBJECT OF THE ARTICLE:
"{topic}"

TITLE RULES — READ CAREFULLY:
The article title must directly reflect the topic above.
- The title must contain the core subject of the topic.
- Do NOT rename, reframe, or find a "catchier angle."
- If the topic is "{topic}", a title like "{topic}: What Enterprise Teams Need to Know in 2026"
  is correct.
- A title that replaces the topic entirely with a sub-theme or buzzword phrase is WRONG
  and will be rejected.
- Example of WRONG behaviour: topic is "Cybersecurity Trends" but title becomes
  "The Agentic Era of Cybersecurity" — this replaces the topic with one sub-angle.
- Example of CORRECT behaviour: topic is "Cybersecurity Trends" and title becomes
  "Cybersecurity Trends in 2026: Five Shifts Reshaping Enterprise Security Posture."

SCOPE RULES:
- If the topic is BROAD (contains words like "trends", "overview", "state of",
  "landscape", "future of"), the article MUST cover multiple distinct themes with
  roughly equal depth. Minimum 4-5 themes for any "trends" topic.
  Do NOT pick the loudest current news angle and write the whole article about it.
- If the topic is SPECIFIC (a product comparison, a named technology, a named event),
  stay tightly focused on that specific subject.

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

LENGTH REQUIREMENTS:
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
- Clearly distinguish:
    (a) vendor marketing claims
    (b) independent analyst findings (Gartner, Forrester, IDC, academic papers)
    (c) practitioner and expert opinion (named researchers, engineers)
    (d) real-world deployment reports and case studies
- For technical topics: use specific product names, version numbers, release dates —
  never vague references like "Microsoft's AI tools"
- Acknowledge known limitations, open questions, and where evidence is genuinely thin
- Do NOT use: "game-changer", "revolutionary", "transformative", "unlock potential",
  "in today's fast-paced world", "seamlessly", or enterprise buzzword phrases

RESEARCH DATA NOTE:
The research data above may contain multiple sections. Treat them as a single unified
source pool. Do not expose or reference the section structure in the article.

CITATIONS:
- Use inline citations [1], [2] throughout main_content
- End main_content with a '### References' section mapping each number to the exact
  source title from AVAILABLE SOURCES

LINKEDIN IDEAS:
Each linkedin_idea must be a concrete angle grounded in a specific observation,
data point, or honest opinion — something a senior enterprise practitioner would
actually post. No generic "AI is changing X" angles.

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
