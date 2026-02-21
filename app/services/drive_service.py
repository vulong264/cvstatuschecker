"""
Google Drive service — lists and downloads CV files from a shared folder.

Authentication options (in priority order):
1. Service account JSON file (GOOGLE_SERVICE_ACCOUNT_FILE env var)
2. OAuth2 via credentials.json + token.json (interactive, for local dev)

Supported CV file types: PDF, DOCX, DOC, TXT, ODT, Google Docs
"""
import io
import os
import logging
from pathlib import Path
from typing import Iterator

from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from app.config import get_settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# MIME types we can process
SUPPORTED_MIME_TYPES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
    "text/plain": ".txt",
    "application/vnd.oasis.opendocument.text": ".odt",
    "application/vnd.google-apps.document": ".docx",   # Google Docs → export as DOCX
}

GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
GOOGLE_DOC_EXPORT_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _build_service():
    """Build and return an authenticated Google Drive service client."""
    settings = get_settings()
    creds = None

    sa_file = settings.google_service_account_file
    if sa_file and Path(sa_file).exists():
        logger.info("Authenticating via service account: %s", sa_file)
        creds = service_account.Credentials.from_service_account_file(
            sa_file, scopes=SCOPES
        )
    else:
        # Fall back to OAuth2 token flow (local development)
        token_path = "token.json"
        creds_path = "credentials.json"

        if Path(token_path).exists():
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not Path(creds_path).exists():
                    raise FileNotFoundError(
                        "Neither service-account.json nor credentials.json found. "
                        "See .env.example for setup instructions."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(token_path, "w") as f:
                f.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


def list_cv_files(folder_id: str | None = None) -> list[dict]:
    """
    Return a list of file metadata dicts from the configured Drive folder.

    Each dict contains: id, name, mimeType, modifiedTime, size
    """
    settings = get_settings()
    folder_id = folder_id or settings.google_drive_folder_id
    if not folder_id:
        raise ValueError("GOOGLE_DRIVE_FOLDER_ID is not set.")

    service = _build_service()
    mime_filter = " or ".join(
        f"mimeType='{m}'" for m in SUPPORTED_MIME_TYPES
    )
    query = f"'{folder_id}' in parents and ({mime_filter}) and trashed=false"

    files = []
    page_token = None
    while True:
        response = (
            service.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)",
                pageToken=page_token,
                pageSize=100,
            )
            .execute()
        )
        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    logger.info("Found %d CV file(s) in folder %s", len(files), folder_id)
    return files


def download_file(file_id: str, mime_type: str) -> tuple[bytes, str]:
    """
    Download a file from Drive and return (content_bytes, file_extension).

    Google Docs are exported as DOCX automatically.
    """
    service = _build_service()

    if mime_type == GOOGLE_DOC_MIME:
        request = service.files().export_media(
            fileId=file_id, mimeType=GOOGLE_DOC_EXPORT_MIME
        )
        ext = ".docx"
    else:
        request = service.files().get_media(fileId=file_id)
        ext = SUPPORTED_MIME_TYPES.get(mime_type, ".bin")

    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    return buffer.getvalue(), ext


def iter_cv_files(folder_id: str | None = None) -> Iterator[tuple[dict, bytes, str]]:
    """
    Yield (file_metadata, content_bytes, extension) for each CV in the folder.
    Skips files that fail to download.
    """
    for file_meta in list_cv_files(folder_id):
        try:
            content, ext = download_file(file_meta["id"], file_meta["mimeType"])
            yield file_meta, content, ext
        except Exception as exc:
            logger.warning("Failed to download %s: %s", file_meta["name"], exc)
