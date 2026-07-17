from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlatformId:
    value: str

    def __post_init__(self) -> None:
        value = self.value.strip().lower()
        if (
            not value
            or not value[0].isalpha()
            or not all(ch.isalnum() or ch in "_-" for ch in value)
        ):
            raise ValueError(f"invalid platform id: {self.value!r}")
        object.__setattr__(self, "value", value)


@dataclass(frozen=True, slots=True)
class EntityId:
    platform: PlatformId
    external_id: str

    def __post_init__(self) -> None:
        value = self.external_id.strip()
        if not value:
            raise ValueError("external_id cannot be empty")
        object.__setattr__(self, "external_id", value)
