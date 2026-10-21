from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_CONTENT = 120_000


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArticleInput(StrictModel):
    url: str = Field(default="", max_length=2048)
    title: str = Field(default="", max_length=300)
    author: str = Field(default="", max_length=200)
    published_at: str = Field(default="", max_length=80)
    content: str = Field(default="", max_length=MAX_CONTENT)
    tags: list[str] = Field(default_factory=list, max_length=20)
    category: str = Field(default="", max_length=80)
    source_kind: Literal["article", "thread", "note"] = "article"

    @model_validator(mode="after")
    def has_input(self):
        self.url = self.url.strip()
        self.content = self.content.strip()
        self.tags = list(dict.fromkeys(t.strip()[:60] for t in self.tags if t.strip()))
        if not self.url and not self.content:
            raise ValueError("请提供链接或文章全文。")
        if self.content and len(self.content) < 20:
            raise ValueError("正文至少需要 20 个字符。")
        return self


class ArticlePatch(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    author: str | None = Field(default=None, max_length=200)
    published_at: str | None = Field(default=None, max_length=80)
    content: str | None = Field(default=None, min_length=20, max_length=MAX_CONTENT)
    tags: list[str] | None = Field(default=None, max_length=20)
    category: str | None = Field(default=None, max_length=80)
    is_read: bool | None = None


class BatchInput(StrictModel):
    articles: list[ArticleInput] = Field(min_length=1, max_length=50)


class Evidence(StrictModel):
    chunk_id: str
    quote: str = Field(min_length=8, max_length=800)


class GroundedPoint(StrictModel):
    label: str = Field(max_length=120)
    text: str = Field(min_length=30, max_length=2500)
    evidence: list[Evidence] = Field(min_length=1, max_length=2)


class KnowledgeCard(StrictModel):
    problem: str = Field(min_length=10, max_length=500)
    method: str = Field(min_length=20, max_length=1000)
    why: str = Field(min_length=5, max_length=800)
    scenarios: list[str] = Field(min_length=1, max_length=8)
    prerequisites: list[str] = Field(min_length=1, max_length=8)
    steps: list[str] = Field(min_length=1, max_length=12)
    limitations: list[str] = Field(min_length=1, max_length=8)
    questions: list[str] = Field(min_length=1, max_length=8)
    evidence: list[Evidence] = Field(min_length=1, max_length=6)


class Rating(StrictModel):
    score: int = Field(ge=1, le=5)
    reason: str = Field(min_length=1, max_length=500)


class Ratings(StrictModel):
    novelty: Rating
    credibility: Rating
    relevance: Rating
    actionability: Rating
    longevity: Rating


class Analysis(StrictModel):
    quick: list[GroundedPoint] = Field(min_length=1, max_length=2)
    standard: list[GroundedPoint] = Field(min_length=2, max_length=7)
    deep: list[GroundedPoint] = Field(min_length=1, max_length=12)
    knowledge: list[KnowledgeCard] = Field(min_length=1, max_length=10)
    category: str = Field(max_length=80)
    tags: list[str] = Field(max_length=6)
    ratings: Ratings
    credibility: str = Field(min_length=1, max_length=1000)


class BriefKnowledgeCard(KnowledgeCard):
    scenarios: list[str] = Field(min_length=1,max_length=2)
    prerequisites: list[str] = Field(min_length=1,max_length=2)
    steps: list[str] = Field(min_length=1,max_length=5)
    limitations: list[str] = Field(min_length=1,max_length=2)
    questions: list[str] = Field(min_length=1,max_length=2)
    evidence: list[Evidence] = Field(min_length=1,max_length=3)


class BriefAnalysis(Analysis):
    """Short sources need distinct reading layers, without a long repetitive report."""
    quick: list[GroundedPoint] = Field(min_length=1,max_length=1)
    standard: list[GroundedPoint] = Field(min_length=2,max_length=2)
    deep: list[GroundedPoint] = Field(min_length=1,max_length=3)
    knowledge: list[BriefKnowledgeCard] = Field(min_length=1,max_length=1)


class AnswerClaim(StrictModel):
    text: str = Field(min_length=1, max_length=2500)
    evidence: list[Evidence] = Field(min_length=1, max_length=6)


class AnswerDraft(StrictModel):
    claims: list[AnswerClaim] = Field(default_factory=list, max_length=12)
    ai_suggestions: list[str] = Field(default_factory=list, max_length=10)
    disagreements: list[AnswerClaim] = Field(default_factory=list, max_length=6)
    gaps: list[str] = Field(default_factory=list, max_length=10)
    insufficient: bool


class ChatInput(StrictModel):
    question: str = Field(min_length=2, max_length=2000)
    session_id: str | None = Field(default=None, max_length=80)
    limit: int = Field(default=8, ge=1, le=15)


class Preferences(StrictModel):
    categories: list[str] = Field(min_length=1, max_length=30)
    interests: str = Field(default="", max_length=1000)
