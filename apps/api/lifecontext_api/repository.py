import json
from pathlib import Path
from uuid import UUID

from .models import (
    PersonCreate,
    PersonRecord,
    PersonaDocumentName,
    PersonaDocumentRecord,
    PersonaDocumentWrite,
    ProfileRecord,
    ProfileWrite,
    VoiceConsentCreate,
    VoiceConsentRecord,
)


class NotFoundError(KeyError):
    pass


class FileRepository:
    """Small local-first store for the v0.1 management API.

    Markdown remains the portable human-facing representation. JSON sidecars keep
    version, evidence and consent metadata separate from prose.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        (self.root / "persons").mkdir(parents=True, exist_ok=True)

    def get_profile(self) -> ProfileRecord | None:
        path = self.root / "profile.json"
        if not path.exists():
            return None
        return ProfileRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def put_profile(self, request: ProfileWrite) -> ProfileRecord:
        record = ProfileRecord(**request.model_dump())
        self._write_json(self.root / "profile.json", record.model_dump(mode="json"))
        return record

    def _person_dir(self, person_id: UUID) -> Path:
        return self.root / "persons" / str(person_id)

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def create_person(self, request: PersonCreate) -> PersonRecord:
        record = PersonRecord(**request.model_dump())
        person_dir = self._person_dir(record.id)
        person_dir.mkdir(parents=True, exist_ok=False)
        self._write_json(person_dir / "person.json", record.model_dump(mode="json"))
        return record

    def get_person(self, person_id: UUID) -> PersonRecord:
        path = self._person_dir(person_id) / "person.json"
        if not path.exists():
            raise NotFoundError(str(person_id))
        return PersonRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def put_persona_document(
        self,
        person_id: UUID,
        document: PersonaDocumentName,
        request: PersonaDocumentWrite,
    ) -> PersonaDocumentRecord:
        self.get_person(person_id)
        persona_dir = self._person_dir(person_id) / "persona"
        metadata_path = persona_dir / f"{document}.json"
        version = 1
        if metadata_path.exists():
            previous = PersonaDocumentRecord.model_validate_json(
                metadata_path.read_text(encoding="utf-8")
            )
            version = previous.version + 1
        record = PersonaDocumentRecord(
            **request.model_dump(), document=document, version=version
        )
        persona_dir.mkdir(parents=True, exist_ok=True)
        (persona_dir / f"{document}.md").write_text(request.content, encoding="utf-8")
        self._write_json(metadata_path, record.model_dump(mode="json"))
        return record

    def get_persona_document(
        self, person_id: UUID, document: PersonaDocumentName
    ) -> PersonaDocumentRecord:
        path = self._person_dir(person_id) / "persona" / f"{document}.json"
        if not path.exists():
            raise NotFoundError(f"{person_id}/{document}")
        return PersonaDocumentRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def grant_voice_consent(
        self, person_id: UUID, request: VoiceConsentCreate
    ) -> VoiceConsentRecord:
        self.get_person(person_id)
        if not request.confirmed_right_to_voice:
            raise ValueError("Voice cloning requires a confirmed right to use this voice.")
        record = VoiceConsentRecord(person_id=person_id, **request.model_dump())
        self._write_json(
            self._person_dir(person_id) / "consents" / f"{record.id}.json",
            record.model_dump(mode="json"),
        )
        return record

    def get_voice_consent(self, person_id: UUID, consent_id: UUID) -> VoiceConsentRecord:
        path = self._person_dir(person_id) / "consents" / f"{consent_id}.json"
        if not path.exists():
            raise NotFoundError(f"{person_id}/{consent_id}")
        record = VoiceConsentRecord.model_validate_json(path.read_text(encoding="utf-8"))
        if record.person_id != person_id:
            raise NotFoundError(f"{person_id}/{consent_id}")
        return record
