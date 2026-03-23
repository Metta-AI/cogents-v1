"""Google Drive capability — search, list, read, upload, and share files."""

from __future__ import annotations

import io
import logging
from typing import Any

from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.io.google.auth import get_service

logger = logging.getLogger(__name__)

_PERMISSION_HINT = "File not found or not shared with this cogent's service account."

# Google Workspace MIME types that need export rather than direct download.
_EXPORT_MIME_TYPES: dict[str, str] = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
    "application/vnd.google-apps.drawing": "image/svg+xml",
}

_FILE_FIELDS = "id, name, mimeType, size, modifiedTime, webViewLink"


# ── IO Models ────────────────────────────────────────────────


class FileInfo(BaseModel):
    id: str
    name: str
    mime_type: str
    size: int | None = None
    modified_time: str | None = None
    web_view_link: str | None = None


class DownloadResult(BaseModel):
    file_id: str
    name: str
    content: str


class UploadResult(BaseModel):
    id: str
    name: str
    web_view_link: str | None = None


class ShareResult(BaseModel):
    file_id: str
    email: str
    role: str


class DriveError(BaseModel):
    error: str


# ── Helpers ──────────────────────────────────────────────────


def _file_info(f: dict[str, Any]) -> FileInfo:
    size = f.get("size")
    return FileInfo(
        id=f["id"],
        name=f.get("name", ""),
        mime_type=f.get("mimeType", ""),
        size=int(size) if size is not None else None,
        modified_time=f.get("modifiedTime"),
        web_view_link=f.get("webViewLink"),
    )


def _is_permission_error(exc: Exception) -> bool:
    from googleapiclient.errors import HttpError

    if isinstance(exc, HttpError):
        return exc.resp.status in (403, 404)
    return False


# ── Capability ───────────────────────────────────────────────


class DriveCapability(Capability):
    """Search, list, read, upload, and share Google Drive files.

    Users share Drive files/folders with the cogent's service account email,
    then the cogent can access them through this capability.
    """

    ALL_OPS = {"search", "list", "get", "download", "upload", "share"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result: dict = {}
        for key in ("ops",):
            old, new = existing.get(key), requested.get(key)
            if old is not None and new is not None:
                result[key] = set(old) & set(new)
            elif old is not None:
                result[key] = old
            elif new is not None:
                result[key] = new
        return result

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        allowed_ops = self._scope.get("ops")
        if allowed_ops is not None and op not in allowed_ops:
            raise PermissionError(
                f"DriveCapability: '{op}' not allowed (allowed: {allowed_ops})"
            )

    def _drive(self) -> Any:
        return get_service("drive", "v3", self._secrets_provider)

    # ── Public methods ───────────────────────────────────────

    def search(self, query: str, limit: int = 20) -> list[FileInfo] | DriveError:
        """Search for files matching a Drive query string."""
        self._check("search")
        try:
            resp = (
                self._drive()
                .files()
                .list(
                    q=query,
                    pageSize=min(limit, 100),
                    fields=f"files({_FILE_FIELDS})",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            return [_file_info(f) for f in resp.get("files", [])]
        except Exception as exc:
            if _is_permission_error(exc):
                return DriveError(error=_PERMISSION_HINT)
            logger.exception("Drive search failed")
            return DriveError(error=str(exc))

    def list(
        self, folder_id: str | None = None, limit: int = 50
    ) -> list[FileInfo] | DriveError:
        """List files in a folder (or root if folder_id is None)."""
        self._check("list")
        try:
            q = f"'{folder_id}' in parents" if folder_id else None
            resp = (
                self._drive()
                .files()
                .list(
                    q=q,
                    pageSize=min(limit, 100),
                    fields=f"files({_FILE_FIELDS})",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            return [_file_info(f) for f in resp.get("files", [])]
        except Exception as exc:
            if _is_permission_error(exc):
                return DriveError(error=_PERMISSION_HINT)
            logger.exception("Drive list failed")
            return DriveError(error=str(exc))

    def get(self, file_id: str) -> FileInfo | DriveError:
        """Get metadata for a single file."""
        self._check("get")
        try:
            f = (
                self._drive()
                .files()
                .get(
                    fileId=file_id,
                    fields=_FILE_FIELDS,
                    supportsAllDrives=True,
                )
                .execute()
            )
            return _file_info(f)
        except Exception as exc:
            if _is_permission_error(exc):
                return DriveError(error=_PERMISSION_HINT)
            logger.exception("Drive get failed")
            return DriveError(error=str(exc))

    def download(self, file_id: str) -> DownloadResult | DriveError:
        """Download file content. Google Workspace files are exported as text."""
        self._check("download")
        try:
            drive = self._drive()
            # First fetch metadata to determine mime type and name.
            meta = (
                drive.files()
                .get(fileId=file_id, fields="id, name, mimeType", supportsAllDrives=True)
                .execute()
            )
            mime = meta.get("mimeType", "")
            name = meta.get("name", "")

            if mime in _EXPORT_MIME_TYPES:
                export_mime = _EXPORT_MIME_TYPES[mime]
                content_bytes: bytes = (
                    drive.files()
                    .export(fileId=file_id, mimeType=export_mime)
                    .execute()
                )
            else:
                from googleapiclient.http import MediaIoBaseDownload

                request = drive.files().get_media(fileId=file_id)
                buf = io.BytesIO()
                downloader = MediaIoBaseDownload(buf, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                content_bytes = buf.getvalue()

            # Best-effort decode to text.
            try:
                content = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                content = content_bytes.decode("latin-1")

            return DownloadResult(file_id=file_id, name=name, content=content)
        except Exception as exc:
            if _is_permission_error(exc):
                return DriveError(error=_PERMISSION_HINT)
            logger.exception("Drive download failed")
            return DriveError(error=str(exc))

    def upload(
        self,
        name: str,
        content: str,
        folder_id: str | None = None,
        mime_type: str = "text/plain",
    ) -> UploadResult | DriveError:
        """Upload a new file to Drive."""
        self._check("upload")
        try:
            from googleapiclient.http import MediaInMemoryUpload

            body: dict[str, Any] = {"name": name}
            if folder_id:
                body["parents"] = [folder_id]

            media = MediaInMemoryUpload(
                content.encode("utf-8"), mimetype=mime_type, resumable=False
            )
            f = (
                self._drive()
                .files()
                .create(
                    body=body,
                    media_body=media,
                    fields="id, name, webViewLink",
                    supportsAllDrives=True,
                )
                .execute()
            )
            return UploadResult(
                id=f["id"],
                name=f.get("name", name),
                web_view_link=f.get("webViewLink"),
            )
        except Exception as exc:
            if _is_permission_error(exc):
                return DriveError(error=_PERMISSION_HINT)
            logger.exception("Drive upload failed")
            return DriveError(error=str(exc))

    def share(
        self, file_id: str, email: str, role: str = "reader"
    ) -> ShareResult | DriveError:
        """Share a file by creating a permission for the given email."""
        self._check("share")
        try:
            self._drive().permissions().create(
                fileId=file_id,
                body={"type": "user", "role": role, "emailAddress": email},
                sendNotificationEmail=False,
                supportsAllDrives=True,
            ).execute()
            return ShareResult(file_id=file_id, email=email, role=role)
        except Exception as exc:
            if _is_permission_error(exc):
                return DriveError(error=_PERMISSION_HINT)
            logger.exception("Drive share failed")
            return DriveError(error=str(exc))

    def __repr__(self) -> str:
        return "<DriveCapability search() list() get() download() upload() share()>"
