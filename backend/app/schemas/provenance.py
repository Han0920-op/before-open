"""Source metadata validates evidence shape, never real-world truth or authorization."""

from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    HttpUrl,
    StringConstraints,
    model_validator,
)

Text = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)]
Source = Literal[
    "user_input", "demo_assumption", "verified_external", "derived", "user_observation", "unknown"
]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ExternalEvidence(FrozenModel):
    source_url: HttpUrl
    observed_at: AwareDatetime
    scope: Text


class SourceField[T](FrozenModel):
    value: T | None
    source: Source
    note: str = ""
    evidence: ExternalEvidence | None = None
    observation_id: Text | None = None
    derived_from: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def consistent_source(self) -> Self:
        if (self.value is None) != (self.source == "unknown"):
            raise ValueError("null requires unknown; known values require a known source")
        if (self.evidence is not None) != (self.source == "verified_external"):
            raise ValueError("external evidence is required only for verified_external")
        if (self.observation_id is not None) != (self.source == "user_observation"):
            raise ValueError("observation_id is required only for user_observation")
        if bool(self.derived_from) != (self.source == "derived"):
            raise ValueError("derived_from is required only for derived values")
        return self
