import json
import os
from pathlib import Path
from uuid import UUID

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .cosyvoice import CosyVoiceClient, pcm16_mono_to_wav
from .harness import HarnessService
from .models import (
    HealthResponse,
    OralHistoryAnswerWrite,
    PersonCreate,
    PersonRecord,
    PersonaDocumentName,
    PersonaDocumentRecord,
    PersonaDocumentWrite,
    ProfileRecord,
    ProfileWrite,
    ThoughtCellReview,
    VoiceConsentCreate,
    VoiceConsentRecord,
)
from .repository import FileRepository, NotFoundError
from .runtime_manager import RuntimeErrorDetail, RuntimeManager
from .voice_profile import VoiceProfileError, VoiceProfileStore


project_root = Path(__file__).resolve().parents[3]
data_dir = Path(os.getenv("LIFECONTEXT_DATA_DIR", str(project_root / "data")))
rawdata_dir = Path(os.getenv("LIFECONTEXT_RAWDATA_DIR", str(project_root / "RAWDATA")))
frontend_dir = project_root / "apps" / "web"
repository = FileRepository(data_dir)
harness = HarnessService(
    rawdata_dir,
    data_dir,
    project_root / "models" / "qwen3-4b" / "download-status.json",
    project_root / "models" / "qwen3-4b" / "Qwen3-4B-Q4_K_M.gguf",
    project_root / ".runtime" / "llama.cpp" / "llama-server.exe",
)
runtime_manager = RuntimeManager(project_root, data_dir)
voice_profile = VoiceProfileStore(data_dir)
cosyvoice = CosyVoiceClient(
    os.getenv("COSYVOICE_BASE_URL", "http://127.0.0.1:50000"),
    float(os.getenv("COSYVOICE_TIMEOUT_SECONDS", "900")),
)

app = FastAPI(
    title="LifeContext L1 Management API",
    version=__version__,
    description="本地优先的人生上下文、人格文档、HARNESS 与 Mindcopy 运行中台。",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class MindcopyChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10_000)
    session_id: str = Field(default="default", min_length=1, max_length=80)


class CloudModelConfigurationWrite(BaseModel):
    enabled: bool = False
    provider: str = Field(default="openai-compatible", min_length=1, max_length=80)
    base_url: str = Field(min_length=8, max_length=500)
    model: str = Field(default="", max_length=200)
    api_key: str = Field(default="", max_length=2_000)
    timeout_seconds: int = Field(default=120, ge=10, le=600)


class MemoryCandidateReview(BaseModel):
    status: str = Field(pattern="^(confirmed|rejected|unreviewed)$")


class MindcopyInferenceParameters(BaseModel):
    temperature: float = Field(default=0.68, ge=0, le=2)
    top_p: float = Field(default=0.95, ge=0.01, le=1)
    top_k: int = Field(default=40, ge=0, le=200)
    repeat_penalty: float = Field(default=1.05, ge=0.5, le=2)
    max_tokens: int = Field(default=700, ge=32, le=2_048)
    seed: int = Field(default=-1, ge=-1, le=2_147_483_647)


class MindcopyConfigurationWrite(BaseModel):
    system_prompt: str = Field(min_length=1, max_length=20_000)
    user_prompt_template: str = Field(min_length=1, max_length=20_000)
    parameters: MindcopyInferenceParameters


class MindcopyPromptPreviewRequest(MindcopyConfigurationWrite):
    message: str = Field(min_length=1, max_length=10_000)


@app.on_event("startup")
def start_harness() -> None:
    harness.start()


@app.on_event("shutdown")
def stop_harness() -> None:
    harness.stop()
    runtime_manager.shutdown()


@app.get("/", include_in_schema=False)
def home() -> RedirectResponse:
    return RedirectResponse("/ui/")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(version=__version__)


@app.get("/v1/harness/summary")
def harness_summary() -> dict:
    return harness.summary()


@app.get("/v1/runtime/status")
def runtime_status() -> dict:
    return runtime_manager.status()


@app.post("/v1/runtime/{service}/start", status_code=202)
def runtime_start(service: str) -> dict:
    try:
        return runtime_manager.start(service)
    except RuntimeErrorDetail as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/runtime/{service}/stop")
def runtime_stop(service: str) -> dict:
    try:
        return runtime_manager.stop(service)
    except RuntimeErrorDetail as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/v1/harness/jobs")
def harness_jobs() -> list[dict]:
    return harness.list_jobs()


@app.get("/v1/thought-cells")
def thought_cells(limit: int = 200, status: str | None = None, kind: str | None = None) -> list[dict]:
    cells = harness.all_thought_cells(max(1, min(limit, 2_000)))
    if status:
        cells = [cell for cell in cells if cell.get("review_status") == status]
    if kind:
        cells = [cell for cell in cells if cell.get("kind") == kind]
    return cells


@app.patch("/v1/thought-cells/{cell_id}/review")
def review_thought_cell(cell_id: str, request: ThoughtCellReview) -> dict:
    try:
        return harness.review_thought_cell(cell_id, request.status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ThoughtCell not found") from exc


@app.get("/v1/profile", response_model=ProfileRecord | None)
def get_profile() -> ProfileRecord | None:
    return repository.get_profile()


@app.put("/v1/profile", response_model=ProfileRecord)
def put_profile(request: ProfileWrite) -> ProfileRecord:
    record = repository.put_profile(request)
    harness.compile_persona_documents()
    return record


@app.get("/v1/persona/{document}")
def get_compiled_persona(document: str) -> dict:
    try:
        return harness.get_persona_document(document)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Persona document not found") from exc


@app.get("/v1/oral-history")
def get_oral_history() -> dict:
    return harness.oral_history()


@app.put("/v1/oral-history/answers/{question_id}")
def put_oral_history_answer(question_id: str, request: OralHistoryAnswerWrite) -> dict:
    try:
        return harness.save_oral_history_answer(question_id, request.answer)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Oral history question not found") from exc


@app.post("/v1/harness/upload", status_code=202)
async def harness_upload(files: list[UploadFile] = File()) -> dict:
    accepted: list[dict] = []
    for upload in files:
        payload = await upload.read()
        if not payload:
            continue
        try:
            path = harness.save_upload(upload.filename or "untitled.txt", payload)
        except OSError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        accepted.append({"filename": path.name, "size": len(payload)})
    return {"accepted": accepted, "rawdata_path": str(harness.raw_dir)}


@app.post("/v1/harness/open-rawdata")
def open_rawdata() -> dict:
    try:
        harness.open_rawdata()
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return {"opened": True, "path": str(harness.raw_dir)}


@app.post("/v1/mindcopy/chat")
def mindcopy_chat(request: MindcopyChatRequest) -> dict:
    try:
        return harness.mindcopy_chat(request.message, request.session_id)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Configured model runtime unavailable") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/v1/mindcopy/config")
def get_mindcopy_config(preview_message: str = "{{USER_MESSAGE}}") -> dict:
    return harness.mindcopy_configuration(preview_message[:10_000])


@app.put("/v1/mindcopy/config")
def put_mindcopy_config(request: MindcopyConfigurationWrite) -> dict:
    return harness.save_mindcopy_configuration(request.model_dump())


@app.post("/v1/mindcopy/prompt-preview")
def preview_mindcopy_prompt(request: MindcopyPromptPreviewRequest) -> dict:
    payload = request.model_dump()
    return harness.preview_mindcopy_prompt(payload.pop("message"), payload)


@app.post("/v1/mindcopy/chat/stream")
def mindcopy_chat_stream(request: MindcopyChatRequest) -> StreamingResponse:
    def stream_events():
        for event in harness.mindcopy_chat_stream(request.message, request.session_id):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(
        stream_events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.get("/v1/cloud-model/config")
def get_cloud_model_config() -> dict:
    return harness.cloud_llm.public_config()


@app.put("/v1/cloud-model/config")
def put_cloud_model_config(request: CloudModelConfigurationWrite) -> dict:
    try:
        return harness.cloud_llm.configure(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/memory/summary")
def memory_summary() -> dict:
    return harness.memory.summary()


@app.get("/v1/memory/candidates")
def memory_candidates(status: str | None = None, limit: int = 200) -> list[dict]:
    return harness.memory.candidates(status=status, limit=limit)


@app.patch("/v1/memory/candidates/{candidate_id}/review")
def review_memory_candidate(candidate_id: str, request: MemoryCandidateReview) -> dict:
    try:
        return harness.memory.review_candidate(candidate_id, request.status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Memory candidate not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/memory/sessions/{session_id}")
def session_memory(session_id: str, limit: int = 100) -> list[dict]:
    return harness.memory.turns(session_id, limit=limit)


@app.get("/v1/voice-profile")
def get_voice_profile() -> dict:
    return voice_profile.get()


@app.post("/v1/voice-profile")
async def put_voice_profile(
    reference_text: str = Form(min_length=1, max_length=2_000),
    confirmed_right_to_voice: bool = Form(),
    reference_wav: UploadFile = File(),
) -> dict:
    payload = await reference_wav.read()
    try:
        return voice_profile.save(
            filename=reference_wav.filename or "reference.wav",
            audio=payload,
            reference_text=reference_text,
            confirmed=confirmed_right_to_voice,
        )
    except VoiceProfileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/voice-profile/preview")
async def preview_voice(tts_text: str = Form(min_length=1, max_length=1_000)) -> Response:
    profile = voice_profile.get()
    if not profile.get("configured"):
        raise HTTPException(status_code=409, detail="Configure a reference voice first")
    try:
        pcm = await cosyvoice.synthesize_zero_shot(
            tts_text=tts_text,
            prompt_text=str(profile["reference_text"]),
            prompt_wav=voice_profile.audio(),
            prompt_filename="reference.wav",
        )
    except VoiceProfileError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail="CosyVoice generation failed. Verify that the reference transcript matches the recording word for word.",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="CosyVoice runtime is unreachable") from exc
    if len(pcm) < 4_800:
        raise HTTPException(status_code=502, detail="CosyVoice returned an invalidly short preview")
    return Response(content=pcm16_mono_to_wav(pcm), media_type="audio/wav")


@app.post("/v1/voice-profile/preview/stream")
async def preview_voice_stream(tts_text: str = Form(min_length=1, max_length=1_000)) -> StreamingResponse:
    profile = voice_profile.get()
    if not profile.get("configured"):
        raise HTTPException(status_code=409, detail="Configure a reference voice first")

    source = cosyvoice.stream_zero_shot(
        tts_text=tts_text,
        prompt_text=str(profile["reference_text"]),
        prompt_wav=voice_profile.audio(),
        prompt_filename="reference.wav",
    )
    try:
        # Fetch the first audio bytes before committing a 200 response. Runtime
        # startup and validation failures can therefore still reach the UI.
        first_chunk = await anext(source)
    except StopAsyncIteration as exc:
        raise HTTPException(status_code=502, detail="CosyVoice returned no streaming audio") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail="CosyVoice generation failed. Verify the voice transcript and runtime state.",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="CosyVoice runtime is unreachable") from exc

    async def stream_body():
        yield first_chunk
        async for chunk in source:
            yield chunk

    return StreamingResponse(
        stream_body(),
        media_type="application/octet-stream",
        headers={
            "X-Audio-Sample-Rate": "24000",
            "X-Audio-Format": "pcm_s16le",
            "Cache-Control": "no-store",
        },
    )


@app.post("/v1/persons", response_model=PersonRecord, status_code=201)
def create_person(request: PersonCreate) -> PersonRecord:
    return repository.create_person(request)


@app.get("/v1/persons/{person_id}", response_model=PersonRecord)
def get_person(person_id: UUID) -> PersonRecord:
    try:
        return repository.get_person(person_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Person not found") from exc


@app.put("/v1/persons/{person_id}/persona/{document}", response_model=PersonaDocumentRecord)
def put_persona_document(
    person_id: UUID, document: PersonaDocumentName, request: PersonaDocumentWrite
) -> PersonaDocumentRecord:
    try:
        return repository.put_persona_document(person_id, document, request)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Person not found") from exc


@app.get("/v1/persons/{person_id}/persona/{document}", response_model=PersonaDocumentRecord)
def get_persona_document(person_id: UUID, document: PersonaDocumentName) -> PersonaDocumentRecord:
    try:
        return repository.get_persona_document(person_id, document)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Persona document not found") from exc


@app.post("/v1/persons/{person_id}/voice-consents", response_model=VoiceConsentRecord, status_code=201)
def grant_voice_consent(person_id: UUID, request: VoiceConsentCreate) -> VoiceConsentRecord:
    try:
        return repository.grant_voice_consent(person_id, request)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="Person not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/persons/{person_id}/voice/synthesize")
async def synthesize_voice(
    person_id: UUID,
    consent_id: UUID = Form(),
    purpose: str = Form(),
    tts_text: str = Form(min_length=1, max_length=5_000),
    prompt_text: str = Form(min_length=1, max_length=2_000),
    prompt_wav: UploadFile = File(),
) -> Response:
    try:
        consent = repository.get_voice_consent(person_id, consent_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=403, detail="Valid voice consent not found") from exc
    if not consent.is_usable_for(purpose):
        raise HTTPException(status_code=403, detail="Voice consent is inactive or out of scope")
    audio = await prompt_wav.read()
    if not audio:
        raise HTTPException(status_code=400, detail="Prompt audio is empty")
    try:
        pcm = await cosyvoice.synthesize_zero_shot(
            tts_text=tts_text,
            prompt_text=prompt_text,
            prompt_wav=audio,
            prompt_filename=prompt_wav.filename or "prompt.wav",
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="CosyVoice service unavailable") from exc
    return Response(
        content=pcm16_mono_to_wav(pcm),
        media_type="audio/wav",
        headers={"Content-Disposition": 'inline; filename="synthesis.wav"'},
    )


if frontend_dir.exists():
    app.mount("/ui", StaticFiles(directory=frontend_dir, html=True), name="frontend")
