"""RFC 9457 problem details and Anis's machine-readable extensions."""

from dataclasses import dataclass

from anis_partners.models._json import field, integer, model_json, object_data, text


@dataclass(frozen=True, slots=True)
class Problem:
    """Keep machine code separate from localized title and detail so callers branch safely."""

    type: str | None = None
    title: str | None = None
    status: int = 0
    code: str | None = None
    detail: str | None = None
    request_id: str | None = None
    extensions: object | None = None

    @classmethod
    def from_json(cls, data: object) -> "Problem":
        """Read RFC fields and preserve documented extensions without interpreting presentation text."""
        value = object_data(data)
        status = field(value, "status")
        return cls(
            text(field(value, "type")),
            text(field(value, "title")),
            integer(status),
            text(field(value, "code")),
            text(field(value, "detail")),
            text(field(value, "requestId")),
            field(value, "extensions"),
        )

    def to_json(self) -> dict[str, object]:
        """Write exact RFC and extension member names for a problem response."""
        return model_json(self)
