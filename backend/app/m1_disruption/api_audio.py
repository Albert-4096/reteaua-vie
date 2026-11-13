"""Audio version of a stop alert (SPEC §6.1 item 15, CONTRACT row „audio”).

    GET /api/closures/{id}/audio/{stopId}.mp3   audio/mpeg, made once at publish

404 NO_AUDIO when there is no MP3 (other closures, no key, budget refused, not yet
made): the QR page then reads the alert's `ttsDescriptionText` with Web Speech ro-RO.
"""

from __future__ import annotations

import re

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.common.errors import not_found
from app.m1_disruption import audio

router = APIRouter(tags=["M1 outputs"])

_ID = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
_STOP = re.compile(r"^[A-Za-z0-9_.:-]{1,40}$")


@router.api_route("/closures/{closure_id}/audio/{stop_id}.mp3", methods=["GET", "HEAD"],
                  response_class=FileResponse,
                  responses={200: {"content": {"audio/mpeg": {}},
                                   "description": "MP3, Romanian, AI-generated voice (ElevenLabs)"},
                             404: {"description": "No MP3: use Web Speech ro-RO on ttsDescriptionText"}})
def stop_audio(closure_id: str, stop_id: str) -> FileResponse:
    path = None
    if _ID.match(closure_id) and _STOP.match(stop_id):
        path = audio.audio_file(closure_id, stop_id)
    if path is None:
        raise not_found("Nu există variantă audio pentru această stație; folosiți Web Speech (ro-RO) / "
                        "no audio for this stop; use Web Speech (ro-RO).", "NO_AUDIO")
    return FileResponse(path, media_type="audio/mpeg",
                        headers={"Cache-Control": "public, max-age=3600",
                                 "Content-Disposition": f'inline; filename="anunt_{closure_id}_{stop_id}.mp3"',
                                 "X-Audio-Label": "AI-generated voice (ElevenLabs)"})
