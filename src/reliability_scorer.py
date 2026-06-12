"""
Rule-based reliability scorer for BlogMaker.

Computes source reliability scores based on domain classification.
No LLM involvement -- purely deterministic scoring.

Tuned for enterprise software, SAP, AI, and practitioner/community sources.
"""

from src.logger import get_logger
from src.models import ReliabilityResult, Source

logger = get_logger("reliability_scorer")

# Promote to Tier 1 — genuine think tanks / standards bodies
_TIER1_OVERRIDES = {
    "carnegieendowment.org",   # Carnegie Endowment for International Peace
    "brookings.edu",            # Brookings Institution
    "rand.org",                 # RAND Corporation
    "cisa.gov",                 # CISA — already Tier 1, confirm
    "nist.gov",                 # NIST — already Tier 1, confirm
    "enisa.europa.eu",          # ENISA — already Tier 1, confirm
    "isc2.org",                 # ISC² — primary cybersecurity workforce research
}

# Demote to Tier 3 — marketing pages, career sites, trade press
_TIER3_OVERRIDES = {
    "cybersecurityguide.org",   # Career guide site
    "aha.org",                  # Hospital association — not a cyber authority
    "cyolo.io",                 # Security vendor blog
    "zerothreat.ai",            # Security vendor statistics page
    "sechard.com",              # Small vendor blog
    "bravurasecurity.com",      # Vendor product page
    "seraphicsecurity.com",     # Small vendor blog
    "softwarestrategiesblog.com", # Personal blog
}

# microsoft.com scoring should distinguish:
# - learn.microsoft.com → Tier 2 (official technical docs)
# - microsoft.com/security/business/* → Tier 3 (product marketing)
def score_microsoft_url(url: str) -> int:
    if "learn.microsoft.com" in url or "techcommunity.microsoft.com" in url:
        return 8  # Tier 2
    return 5      # Tier 3 — product marketing


# =============================================================================
# Domain -> Score Mapping
# =============================================================================

DOMAIN_SCORES: dict[str, float] = {

    # ---- Tier 1: Academic & Peer-Reviewed (10) ----
    "arxiv.org": 10,
    "scholar.google.com": 10,
    "nature.com": 10,
    "science.org": 10,
    "sciencedirect.com": 10,
    "ieee.org": 10,
    "ieeexplore.ieee.org": 10,
    "acm.org": 10,
    "dl.acm.org": 10,
    "nber.org": 10,
    "ssrn.com": 10,
    "jstor.org": 10,
    "springer.com": 10,
    "wiley.com": 10,
    "elsevier.com": 10,
    "cambridge.org": 10,
    "mit.edu": 10,
    "stanford.edu": 10,
    "harvard.edu": 10,
    "oxford.ac.uk": 10,
    "ox.ac.uk": 10,
    "cam.ac.uk": 10,
    "iitb.ac.in": 10,
    "iitd.ac.in": 10,
    "iitm.ac.in": 10,

    # ---- Tier 1: Intergovernmental / Government (10) ----
    "oecd.org": 10,
    "imf.org": 10,
    "worldbank.org": 10,
    "un.org": 10,
    "who.int": 10,
    "ilo.org": 10,
    "europa.eu": 10,
    "bis.org": 10,
    "weforum.org": 10,
    "brookings.edu": 10,
    "rand.org": 10,
    "pewresearch.org": 10,
    "nist.gov": 10,
    "sec.gov": 10,
    "ecb.europa.eu": 10,
    "treasury.gov": 10,
    "federalreserve.gov": 10,
    "rbi.org.in": 10,
    "centralbank.ae": 10,
    "adgm.com": 10,
    "difc.ae": 10,
    "whitehouse.gov": 10,
    "congress.gov": 10,
    "gov.uk": 10,

    # ---- Tier 1: Official Vendor Documentation (9) ----
    # Microsoft
    "learn.microsoft.com": 9,
    "techcommunity.microsoft.com": 9,
    "microsoft.com": 8,
    "azure.microsoft.com": 9,
    "blogs.microsoft.com": 8,
    "devblogs.microsoft.com": 9,

    # SAP
    "news.sap.com": 9,
    "community.sap.com": 9,
    "help.sap.com": 9,
    "blogs.sap.com": 8,
    "sap.com": 8,
    "asug.com": 8,
    "sapinsider.org": 8,

    # Google / Alphabet
    "cloud.google.com": 9,
    "ai.google": 9,
    "research.google": 9,
    "blog.google": 8,
    "deepmind.google": 9,
    "deepmind.com": 9,

    # AWS / Amazon
    "aws.amazon.com": 9,
    "aws.amazon.com/blogs": 9,

    # OpenAI / Anthropic / AI Labs
    "openai.com": 9,
    "anthropic.com": 9,
    "mistral.ai": 8,
    "huggingface.co": 8,

    # NVIDIA
    "developer.nvidia.com": 9,
    "blogs.nvidia.com": 8,
    "nvidia.com": 8,

    # Salesforce / ServiceNow
    "developer.salesforce.com": 8,
    "trailhead.salesforce.com": 8,
    "developer.servicenow.com": 8,

    # IBM
    "research.ibm.com": 9,
    "ibm.com": 7,

    # ---- Tier 2: Technology Analyst Firms (9) ----
    "gartner.com": 9,
    "forrester.com": 9,
    "idc.com": 8,
    "451research.com": 8,

    # ---- Tier 2: Consulting & Research Firms (8) ----
    "mckinsey.com": 8,
    "deloitte.com": 8,
    "pwc.com": 8,
    "bcg.com": 8,
    "accenture.com": 8,
    "ey.com": 8,
    "kpmg.com": 8,
    "bain.com": 8,
    "hbr.org": 8,
    "statista.com": 7,

    # ---- Tier 2: Premium News & Business Press (8-9) ----
    "reuters.com": 9,
    "bloomberg.com": 9,
    "ft.com": 9,
    "wsj.com": 9,
    "economist.com": 9,
    "bbc.com": 8,
    "bbc.co.uk": 8,
    "nytimes.com": 8,
    "washingtonpost.com": 8,
    "apnews.com": 8,
    "cnbc.com": 7,

    # ---- Tier 2: Enterprise & Tech Publications (7-8) ----
    "technologyreview.com": 8,  # MIT Tech Review
    "infoq.com": 8,
    "theregister.com": 7,
    "zdnet.com": 7,
    "computerworld.com": 7,
    "cio.com": 7,
    "arstechnica.com": 7,
    "wired.com": 7,
    "venturebeat.com": 7,
    "techcrunch.com": 6,
    "theverge.com": 6,
    "thenextweb.com": 6,
    "businessinsider.com": 6,
    "forbes.com": 6,
    "fortune.com": 7,
    "siliconangle.com": 6,
    "cnet.com": 6,
    "engadget.com": 5,

    # ---- Tier 2: Think Tanks (8) ----
    "oxfordinternetinstitute.org": 9,
    "oii.ox.ac.uk": 9,
    "ainowinstitute.org": 8,
    "partnershiponai.org": 8,
    "futureoflife.org": 7,
    "allenai.org": 9,

    # ---- Tier 3: Practitioner Newsletters & Long-form (6-7) ----
    # These are intentionally NOT penalised -- they are curated expert content
    "stratechery.com": 7,
    "importai.net": 7,        # Jack Clark's Import AI
    "deeplearning.ai": 7,     # Andrew Ng's The Batch
    "lastweekinai.com": 6,
    "thesequence.io": 6,
    "interconnects.ai": 7,    # Nathan Lambert
    "transformer-circuits.pub": 8,  # Anthropic interpretability

    # ---- Tier 3: Community & Aggregators (4-6) ----
    # Scored lower but NOT zero -- they often link to primary sources
    "medium.com": 4,
    "substack.com": 5,        # raised from 4: many credible practitioner substacks
    "towardsdatascience.com": 5,
    "hackernoon.com": 4,
    "dev.to": 4,
    "reddit.com": 3,
    "quora.com": 3,
    "wikipedia.org": 5,
    "stackoverflow.com": 5,

    # ---- Tier 3: Video / Podcast Platforms (5) ----
    # YouTube and podcast links are valid citations for practitioner opinion
    # They are not scored low just because of the platform
    "youtube.com": 5,
    "youtu.be": 5,
    "podcasts.apple.com": 5,
    "open.spotify.com": 5,
    "lexfridman.com": 7,      # Lex Fridman -- direct site scored higher
}


# Category labels for human-readable breakdown
SCORE_CATEGORIES: dict[int, str] = {
    10: "Tier 1 -- Academic / Government / Intergovernmental",
    9:  "Tier 1 -- Official Vendor Docs / Analyst Firms / Premium News",
    8:  "Tier 2 -- Consulting / Enterprise Publications / Tech Analysts",
    7:  "Tier 2 -- Enterprise Tech Journalism / Think Tanks / Practitioner Newsletters",
    6:  "Tier 3 -- Tech News",
    5:  "Tier 3 -- Community Platforms / Video / Unknown",
    4:  "Tier 3 -- Blogs & Aggregators",
    3:  "Tier 3 -- User-Generated Content",
}

DEFAULT_SCORE = 5.0

PUBLISHER_SCORES: dict[str, float] = {
    # Intergovernmental
    "oecd": 10, "imf": 10, "world bank": 10, "ilo": 10,
    "wef": 10, "united nations": 10, "who": 10,
    # Government
    "rbi": 10, "sebi": 10, "npci": 10, "niti aayog": 10,
    "central bank": 10, "federal reserve": 10,
    # Academic
    "harvard": 10, "mit": 10, "stanford": 10,
    "oxford": 10, "cambridge": 10, "iit": 10,
    # Vendor / Official
    "microsoft": 8, "sap": 8, "google": 8, "amazon": 8,
    "aws": 9, "openai": 9, "anthropic": 9, "nvidia": 8,
    "ibm research": 9, "deepmind": 9,
    # SAP Ecosystem
    "asug": 8, "sapinsider": 8,
    # Analyst
    "gartner": 9, "forrester": 9, "idc": 8,
    # Consulting
    "mckinsey": 8, "deloitte": 8, "pwc": 8, "bcg": 8, "bain": 8,
    # Premium News
    "reuters": 9, "bloomberg": 9, "financial times": 9, "ft": 9,
    "wall street journal": 9, "wsj": 9, "economist": 9,
    # Enterprise Tech Press
    "mit technology review": 8, "infoq": 8, "the register": 7,
    "wired": 7, "ars technica": 7,
    # Named practitioners (YouTube/podcast sources)
    "andrej karpathy": 8, "karpathy": 8,
    "geoffrey hinton": 9, "hinton": 9,
    "yann lecun": 9, "lecun": 9,
    "andrew ng": 8, "ng": 7,
    "lex fridman": 7, "fridman": 7,
    "demis hassabis": 9, "hassabis": 9,
    "fei-fei li": 9,
    "jack clark": 7,
}


class ReliabilityScorer:
    """Rule-based reliability scorer for research sources."""

    def calculate_reliability(self, sources: list[Source]) -> ReliabilityResult:
        """
        Calculate an overall reliability score from the actual sources used.

        Scoring is purely rule-based -- no LLM involvement.
        Each source domain is matched against a predetermined score table.
        The overall score is the weighted average across all sources.

        Practitioner sources (YouTube, Substack, podcasts) are treated as
        valid citations and scored on their own tier -- they are not penalised
        for being non-traditional publication formats.

        Args:
            sources: List of Source objects with populated domains.

        Returns:
            ReliabilityResult with score, explanation, breakdown, and per-source details.
        """
        if not sources:
            return ReliabilityResult(
                score=0.0,
                explanation="No sources available for scoring.",
                source_breakdown={},
                source_details=[],
            )

        scored_sources: list[tuple[Source, float]] = []
        breakdown: dict[str, list[str]] = {}
        source_details: list[dict] = []

        for source in sources:
            domain_score = self._score_domain(source.domain, source.url)
            publisher_score = self._score_publisher(source.publisher)

            # Take the highest score between domain and publisher match
            score = max(domain_score, publisher_score)

            category = SCORE_CATEGORIES.get(int(score), f"Score {int(score)}")

            source.reliability_score = score
            source.tier = self._classify_tier(score)
            source.detected_category = category
            scored_sources.append((source, score))

            source_details.append({
                "url": source.url,
                "domain": source.domain,
                "publisher": source.publisher,
                "score": score,
                "tier": source.tier,
                "detected_category": category,
                "title": source.title,
            })

            if category not in breakdown:
                breakdown[category] = []
            breakdown[category].append(
                source.domain or source.publisher or source.url
            )

            logger.debug(
                "  Source: %-40s domain=%-30s publisher=%-20s "
                "tier=%d score=%.0f (%s)",
                source.url[:50],
                source.domain,
                source.publisher,
                source.tier,
                score,
                category,
            )

        total_score = sum(score for _, score in scored_sources)
        avg_score = round(total_score / len(scored_sources), 1)

        explanation = self._build_explanation(scored_sources, avg_score, breakdown)

        unclassified = [
            d["domain"] for d in source_details
            if d["score"] == DEFAULT_SCORE and d["domain"]
        ]
        if unclassified:
            logger.info(
                "Unclassified domains (scored as %.0f): %s",
                DEFAULT_SCORE, ", ".join(unclassified),
            )

        logger.info(
            "Reliability score: %.1f/10 from %d sources", avg_score, len(sources)
        )

        return ReliabilityResult(
            score=avg_score,
            explanation=explanation,
            source_breakdown=breakdown,
            source_details=source_details,
        )

    def _score_domain(self, domain: str, url: str | None = None) -> float:
        """
        Look up a domain's reliability score.

        Matching order:
          1. Exact match on normalised domain
          2. Parent domain walk (handles subdomains, e.g. insights.mckinsey.com)
          3. TLD-based rules (.gov, .edu, .ac.*, .int)
          4. Default score (5.0)
        """
        if not domain:
            return DEFAULT_SCORE

        domain = domain.lower().strip()

        # Check microsoft.com URL specific scoring
        if url and "microsoft.com" in url.lower():
            return float(score_microsoft_url(url))

        # Check overrides first (exact match)
        if domain in _TIER1_OVERRIDES:
            return 10.0
        if domain in _TIER3_OVERRIDES:
            return 5.0

        # 1. Exact match in DOMAIN_SCORES
        if domain in DOMAIN_SCORES:
            return DOMAIN_SCORES[domain]

        # 2. Parent domain walk
        parts = domain.split(".")
        for i in range(1, len(parts)):
            parent = ".".join(parts[i:])
            if parent in _TIER1_OVERRIDES:
                return 10.0
            if parent in _TIER3_OVERRIDES:
                return 5.0
            if parent in DOMAIN_SCORES:
                return DOMAIN_SCORES[parent]

        # 3. TLD-based rules
        if any(domain.endswith(tld) for tld in (
            ".gov", ".gov.uk", ".gov.au", ".gov.in",
            ".gov.ae", ".gov.sg",
        )):
            return 10.0
        if any(domain.endswith(tld) for tld in (
            ".edu", ".ac.uk", ".ac.in", ".ac.ae",
        )):
            return 10.0
        if domain.endswith(".int"):
            return 10.0
        if domain.endswith(".org"):
            return 7.0

        return DEFAULT_SCORE

    def _score_publisher(self, publisher: str) -> float:
        """Score based on publisher name extracted from page title."""
        if not publisher:
            return DEFAULT_SCORE

        publisher_lower = publisher.lower()
        for key, score in PUBLISHER_SCORES.items():
            if key in publisher_lower:
                return score

        return DEFAULT_SCORE

    @staticmethod
    def _classify_tier(score: float) -> int:
        """Classify a numeric score into a tier number (1 = best)."""
        if score >= 9:
            return 1
        if score >= 7:
            return 2
        return 3

    def _build_explanation(
        self,
        scored_sources: list[tuple[Source, float]],
        avg_score: float,
        breakdown: dict[str, list[str]],
    ) -> str:
        """Build a human-readable explanation of the reliability score."""
        parts: list[str] = []

        for label, domains in sorted(breakdown.items(), reverse=True):
            unique_domains = list(dict.fromkeys(domains))
            count = len(unique_domains)
            sample = ", ".join(unique_domains[:3])
            if count > 3:
                sample += f" (+{count - 3} more)"
            parts.append(f"{count}x {label}: {sample}")

        breakdown_text = "\n".join(f"  - {part}" for part in parts)
        total = len(scored_sources)

        return (
            f"Reliability Score: {avg_score}/10\n"
            f"Based on {total} source{'s' if total != 1 else ''}:\n"
            f"{breakdown_text}\n"
            f"\nScoring: Tier 1 (academic/government/official vendor docs) = 9-10, "
            f"Tier 2 (analyst firms/consulting/premium news/enterprise tech press) = 7-9, "
            f"Tier 3 (tech news/community/video/practitioner blogs) = 4-7, "
            f"Unknown = 5."
        )