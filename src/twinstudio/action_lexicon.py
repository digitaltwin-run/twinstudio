from __future__ import annotations

import re
from collections import deque
from functools import lru_cache
from importlib.resources import files
from typing import Iterable

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from twinstudio.evolution_models import ActionRelation, ActionSearchSpec, GoalVariant
from twinstudio.model_validation import require_unique_attribute


class ActionLexeme(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    lemma: str
    parents: list[str] = Field(default_factory=list)
    children: list[str] = Field(default_factory=list)
    related: list[str] = Field(default_factory=list)
    opposites: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class ActionLexiconCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_version: str
    title: str
    notes: list[str] = Field(default_factory=list)
    actions: list[ActionLexeme] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "ActionLexiconCatalog":
        require_unique_attribute(self.actions, "id", "Action lexeme IDs")
        return self


_ALIASES = {
    "improve": "modify",
    "improving": "modify",
    "enhance": "modify",
    "optimize": "modify",
    "optimise": "modify",
    "fix": "repair",
    "fixing": "repair",
    "hold": "support",
    "mount": "attach",
    "mounting": "attach",
    "secure": "fasten",
    "securely": "fasten",
    "cooling": "cool",
    "ventilate": "vent",
    "protecting": "protect",
    "joining": "join",
    "connecting": "connect",
    "detach": "separate",
    "disconnect": "separate",
    "reduce": "remove",
    "minimize": "remove",
    "minimise": "remove",
    "keep": "maintain",
    "retain": "maintain",
    "monitor": "observe",
    "detect": "sense",
    "inspect": "verify",
    "validate": "verify",
}


def normalize_action(value: str) -> str:
    token = re.sub(r"[^a-z0-9_ -]+", "", value.strip().lower()).replace(" ", "_")
    if token.endswith("ing") and len(token) > 5:
        token = token[:-3]
    elif token.endswith("ed") and len(token) > 4:
        token = token[:-2]
    elif token.endswith("s") and len(token) > 4:
        token = token[:-1]
    return _ALIASES.get(token, token)


@lru_cache(maxsize=1)
def load_action_lexicon() -> ActionLexiconCatalog:
    source = files("twinstudio").joinpath("data/action_lexicon.yaml")
    return ActionLexiconCatalog.model_validate(yaml.safe_load(source.read_text(encoding="utf-8")))


class ActionLexicon:
    """Curated verb hierarchy used to break goal wording fixation.

    The catalog intentionally stays finite and auditable. It does not claim to be
    a complete thesaurus. Unknown verbs remain valid custom seeds and can still
    be connected to explicitly supplied seed verbs in the evolution program.
    """

    def __init__(self, catalog: ActionLexiconCatalog | None = None):
        self.catalog = catalog or load_action_lexicon()
        self.by_id = {item.id: item for item in self.catalog.actions}
        self.reverse_children: dict[str, set[str]] = {}
        for item in self.catalog.actions:
            for child in item.children:
                self.reverse_children.setdefault(child, set()).add(item.id)

    def resolve(self, value: str) -> ActionLexeme | None:
        token = normalize_action(value)
        if token in self.by_id:
            return self.by_id[token]
        for item in self.catalog.actions:
            if normalize_action(item.lemma) == token:
                return item
        return None

    def capabilities(self, action_id: str) -> list[str]:
        item = self.by_id.get(normalize_action(action_id))
        return list(item.capabilities) if item else []

    def assumptions(self, action_id: str) -> list[str]:
        item = self.by_id.get(normalize_action(action_id))
        return list(item.assumptions) if item else []

    def expand(
        self,
        *,
        seed_verb: str,
        statement: str,
        object_phrase: str,
        spec: ActionSearchSpec,
    ) -> list[GoalVariant]:
        normalized_seed = normalize_action(seed_verb)
        seed_item = self.resolve(normalized_seed)
        canonical_seed = seed_item.id if seed_item else normalized_seed

        records: dict[str, tuple[ActionRelation, str | None, int, str]] = {
            canonical_seed: (ActionRelation.SEED, None, 0, "Original or normalized goal action.")
        }

        if seed_item:
            self._walk(
                [seed_item.id],
                direction="parents",
                max_depth=spec.up_depth,
                relation=ActionRelation.HYPERNYM,
                records=records,
            )
            self._walk(
                [seed_item.id],
                direction="children",
                max_depth=spec.down_depth,
                relation=ActionRelation.HYPONYM,
                records=records,
            )
            self._sideways(seed_item, spec.sideways_depth, records)
            if spec.include_opposites:
                for opposite in seed_item.opposites:
                    key = normalize_action(opposite)
                    records.setdefault(
                        key,
                        (
                            ActionRelation.OPPOSITE,
                            seed_item.id,
                            1,
                            "Opposite action used to challenge whether the requested change direction is necessary.",
                        ),
                    )

        for explicit in spec.seed_verbs:
            key = normalize_action(explicit)
            records.setdefault(
                key,
                (
                    ActionRelation.CUSTOM,
                    canonical_seed,
                    0,
                    "Additional action seed supplied by the evolution program.",
                ),
            )

        ordered = sorted(
            records.items(),
            key=lambda item: (
                _relation_rank(item[1][0]),
                item[1][2],
                item[0],
            ),
        )[: spec.max_terms]
        variants: list[GoalVariant] = []
        for index, (verb_id, (relation, source, depth, rationale)) in enumerate(ordered, start=1):
            lexeme = self.by_id.get(verb_id)
            lemma = lexeme.lemma if lexeme else verb_id.replace("_", " ")
            variants.append(
                GoalVariant(
                    node_id=f"goal-{index:03d}-{_slug(verb_id)}",
                    phrase=_rewrite_goal(statement, seed_verb, lemma, object_phrase),
                    verb=lemma,
                    relation=relation,
                    parent_id=source,
                    depth=depth,
                    assumptions=[rationale] if rationale else [],
                    source="catalog" if lexeme else "derived",
                )
            )
        return variants

    def _walk(
        self,
        starts: Iterable[str],
        *,
        direction: str,
        max_depth: int,
        relation: ActionRelation,
        records: dict[str, tuple[ActionRelation, str | None, int, str]],
    ) -> None:
        if max_depth <= 0:
            return
        queue = deque((start, 0) for start in starts)
        seen = set(starts)
        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            item = self.by_id.get(current)
            if not item:
                continue
            neighbors = getattr(item, direction)
            for neighbor in neighbors:
                key = normalize_action(neighbor)
                if key not in records:
                    wording = (
                        "More general action that loosens commitment to the original mechanism."
                        if relation == ActionRelation.HYPERNYM
                        else "More specific action that exposes an alternative implementation mechanism."
                    )
                    records[key] = (relation, current, depth + 1, wording)
                if key not in seen:
                    seen.add(key)
                    queue.append((key, depth + 1))

    def _sideways(
        self,
        seed: ActionLexeme,
        depth: int,
        records: dict[str, tuple[ActionRelation, str | None, int, str]],
    ) -> None:
        if depth <= 0:
            return
        frontier = {seed.id}
        seen = {seed.id}
        for level in range(1, depth + 1):
            next_frontier: set[str] = set()
            for current in frontier:
                item = self.by_id.get(current)
                if not item:
                    continue
                neighbors = set(item.related)
                for parent in item.parents:
                    parent_item = self.by_id.get(normalize_action(parent))
                    if parent_item:
                        neighbors.update(parent_item.children)
                for neighbor in neighbors:
                    key = normalize_action(neighbor)
                    if key == seed.id:
                        continue
                    records.setdefault(
                        key,
                        (
                            ActionRelation.SIBLING,
                            current,
                            level,
                            "Adjacent action reached sideways through a shared parent or related mechanism.",
                        ),
                    )
                    if key not in seen:
                        seen.add(key)
                        next_frontier.add(key)
            frontier = next_frontier


def extract_goal_verb(statement: str) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z_-]*", statement)
    if not words:
        return "change"
    # Skip common soft prefixes used in change requests.
    prefixes = {"please", "could", "would", "should", "need", "want", "make", "let", "to"}
    for word in words[:8]:
        normalized = normalize_action(word)
        if normalized not in prefixes:
            return normalized
    return normalize_action(words[0])


def _rewrite_goal(statement: str, seed: str, replacement: str, object_phrase: str) -> str:
    if not statement.strip():
        return f"{replacement.capitalize()} {object_phrase}".strip()
    pattern = re.compile(rf"\b{re.escape(seed)}\b", re.IGNORECASE)
    if pattern.search(statement):
        return pattern.sub(replacement, statement, count=1)
    first_word = re.compile(r"\b[A-Za-z][A-Za-z_-]*\b")
    match = first_word.search(statement)
    if match:
        return statement[: match.start()] + replacement.capitalize() + statement[match.end() :]
    return f"{replacement.capitalize()} {object_phrase or statement}".strip()


def _relation_rank(relation: ActionRelation | str) -> int:
    value = relation.value if isinstance(relation, ActionRelation) else str(relation)
    return {
        ActionRelation.SEED.value: 0,
        ActionRelation.HYPERNYM.value: 1,
        ActionRelation.HYPONYM.value: 2,
        ActionRelation.SIBLING.value: 3,
        ActionRelation.RELATED.value: 4,
        ActionRelation.OPPOSITE.value: 5,
        ActionRelation.CUSTOM.value: 6,
    }.get(value, 99)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "action"
