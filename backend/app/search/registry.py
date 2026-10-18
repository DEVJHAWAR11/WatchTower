"""Curated India-first source registry plus ATS/feed URL patterns.

These are *candidates*: intake always re-validates them (SSRF-safe fetch, robots, relevance) before use, so a
stale entry just drops out instead of creating a broken watch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RegistryEntry:
    name: str
    url: str
    keywords: tuple[str, ...]
    categories: tuple[str, ...]
    kind: str = "page"


REGISTRY: list[RegistryEntry] = [
    # Central exams & results
    RegistryEntry("SSC (Staff Selection Commission)", "https://ssc.gov.in/",
                  ("ssc", "cgl", "chsl", "mts", "gd", "cpo", "staff selection", "je", "stenographer"),
                  ("exams-results", "government")),
    RegistryEntry("UPSC What's New", "https://upsc.gov.in/whats-new",
                  ("upsc", "civil services", "ias", "cse", "nda", "cds", "ese", "capf", "epfo"),
                  ("exams-results", "government")),
    RegistryEntry("UPSC Active Examinations", "https://upsc.gov.in/examinations/active-exams",
                  ("upsc", "civil services", "nda", "cds", "notification"), ("exams-results",)),
    RegistryEntry("NTA", "https://nta.ac.in/", ("nta", "national testing agency", "cuet", "neet", "jee", "ugc net"),
                  ("exams-results", "admissions")),
    RegistryEntry("JEE Main", "https://jeemain.nta.nic.in/", ("jee", "jee main", "jee mains", "b.tech", "nit"),
                  ("exams-results", "admissions")),
    RegistryEntry("NEET UG", "https://neet.nta.nic.in/", ("neet", "neet ug", "mbbs", "medical"),
                  ("exams-results", "admissions")),
    RegistryEntry("CUET UG", "https://cuet.nta.nic.in/", ("cuet", "cuet ug", "central university"),
                  ("exams-results", "admissions")),
    RegistryEntry("UGC NET", "https://ugcnet.nta.nic.in/", ("ugc net", "net jrf", "jrf"), ("exams-results",)),
    RegistryEntry("CBSE", "https://www.cbse.gov.in/", ("cbse", "class 10", "class 12", "board exam", "date sheet"),
                  ("exams-results",)),
    RegistryEntry("CBSE Results", "https://results.cbse.nic.in/", ("cbse result", "board result", "class 10 result",
                  "class 12 result"), ("exams-results",)),
    RegistryEntry("IBPS", "https://www.ibps.in/", ("ibps", "bank po", "clerk", "rrb po", "so", "banking"),
                  ("exams-results", "jobs")),
    RegistryEntry("SBI Careers", "https://sbi.co.in/web/careers", ("sbi", "sbi po", "sbi clerk", "state bank"),
                  ("jobs", "exams-results")),
    RegistryEntry("RRB Chandigarh", "https://www.rrbcdg.gov.in/", ("rrb", "railway", "ntpc", "group d", "alp", "rrb je"),
                  ("exams-results", "jobs")),
    RegistryEntry("JoSAA", "https://josaa.nic.in/", ("josaa", "counselling", "iit", "nit", "seat allotment"),
                  ("admissions",)),
    RegistryEntry("CAT (IIM)", "https://iimcat.ac.in/", ("cat", "iim", "mba entrance"), ("exams-results", "admissions")),
    RegistryEntry("OJEE", "https://ojee.nic.in/", ("ojee", "odisha joint entrance"), ("exams-results", "admissions")),
    # State PSCs
    RegistryEntry("TNPSC", "https://www.tnpsc.gov.in/", ("tnpsc", "tamil nadu psc", "group 4", "group 2"), ("exams-results",)),
    RegistryEntry("MPSC", "https://mpsc.gov.in/", ("mpsc", "maharashtra psc", "rajyaseva"), ("exams-results",)),
    RegistryEntry("BPSC", "https://bpsc.bih.nic.in/", ("bpsc", "bihar psc", "bihar teacher"), ("exams-results",)),
    RegistryEntry("UPPSC", "https://uppsc.up.nic.in/", ("uppsc", "up psc", "pcs"), ("exams-results",)),
    RegistryEntry("RPSC", "https://rpsc.rajasthan.gov.in/", ("rpsc", "rajasthan psc", "ras"), ("exams-results",)),
    RegistryEntry("WBPSC", "https://wbpsc.gov.in/", ("wbpsc", "west bengal psc", "wbcs"), ("exams-results",)),
    RegistryEntry("OPSC", "https://www.opsc.gov.in/", ("opsc", "odisha psc", "ocs"), ("exams-results",)),
    RegistryEntry("KPSC", "https://kpsc.kar.nic.in/", ("kpsc", "karnataka psc", "kas"), ("exams-results",)),
    RegistryEntry("APPSC", "https://psc.ap.gov.in/", ("appsc", "andhra psc", "group 1"), ("exams-results",)),
    # Scholarships, jobs, government
    RegistryEntry("National Scholarship Portal", "https://scholarships.gov.in/",
                  ("nsp", "scholarship", "national scholarship", "post matric", "pre matric", "merit scholarship"),
                  ("scholarships",)),
    RegistryEntry("AICTE", "https://www.aicte-india.org/", ("aicte", "pragati", "saksham", "internship", "approval"),
                  ("scholarships", "government")),
    RegistryEntry("Employment News", "https://www.employmentnews.gov.in/",
                  ("government job", "sarkari", "employment news", "vacancy", "recruitment"), ("jobs", "government")),
    RegistryEntry("National Career Service", "https://www.ncs.gov.in/", ("ncs", "job fair", "career service"), ("jobs",)),
    RegistryEntry("ISRO Careers", "https://www.isro.gov.in/Careers.html", ("isro", "scientist", "space"), ("jobs",)),
    # Markets
    RegistryEntry("SEBI", "https://www.sebi.gov.in/", ("sebi", "circular", "drhp", "regulation"), ("ipo", "government")),
    RegistryEntry("NSE upcoming issues", "https://www.nseindia.com/market-data/all-upcoming-issues-ipo",
                  ("ipo", "nse", "upcoming ipo", "public issue", "sme ipo"), ("ipo",)),
    RegistryEntry("BSE public issues", "https://www.bseindia.com/markets/PublicIssues/IPOIssues_new.aspx",
                  ("ipo", "bse", "public issue"), ("ipo",)),
]

# Applicant-tracking-system JSON endpoints for company career watches.
ATS_PATTERNS: list[tuple[str, str]] = [
    ("greenhouse", "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"),
    ("lever", "https://api.lever.co/v0/postings/{slug}?mode=json"),
    ("ashby", "https://api.ashbyhq.com/posting-api/job-board/{slug}"),
    ("workable", "https://apply.workable.com/api/v1/widget/accounts/{slug}"),
]

_WORD = re.compile(r"[a-z0-9.+]+")


@dataclass
class RegistryMatch:
    entry: RegistryEntry
    score: float
    matched: list[str] = field(default_factory=list)


def match_registry(text: str, category: str | None = None, limit: int = 4) -> list[RegistryMatch]:
    low = " " + " ".join(_WORD.findall(text.lower())) + " "
    out: list[RegistryMatch] = []
    for e in REGISTRY:
        matched = [k for k in e.keywords if f" {k} " in low]
        if not matched:
            continue
        score = sum(len(k.split()) + 0.5 for k in matched)
        if category and category in e.categories:
            score += 1.0
        out.append(RegistryMatch(e, score, matched))
    out.sort(key=lambda m: -m.score)
    return out[:limit]


def company_slugs(company: str) -> list[str]:
    base = re.sub(r"[^a-z0-9 ]", "", company.lower()).strip()
    if not base:
        return []
    words = base.split()
    cands = {"".join(words), "-".join(words)}
    if words:
        cands.add(words[0])
    return [c for c in cands if 2 <= len(c) <= 40]


def ats_candidates(company: str) -> list[tuple[str, str]]:
    return [(name, pattern.format(slug=slug)) for slug in company_slugs(company) for name, pattern in ATS_PATTERNS]


def github_release_feed(text: str) -> list[str]:
    out = []
    for owner, repo in re.findall(r"github\.com/([A-Za-z0-9-]{1,39})/([A-Za-z0-9_.-]{1,100})", text):
        out.append(f"https://github.com/{owner}/{repo.removesuffix('.git')}/releases.atom")
    return out
