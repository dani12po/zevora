"""Safe, bounded processing for chat attachments."""

import base64
import binascii
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path


TEXT_TYPES = {
    'text/plain', 'text/csv', 'text/markdown', 'text/x-python',
    'text/javascript', 'text/typescript', 'application/json',
    'application/xml', 'application/yaml', 'text/yaml',
}
IMAGE_TYPES = {'image/png', 'image/jpeg', 'image/webp', 'image/gif'}
PDF_TYPE = 'application/pdf'
MAX_TEXT_BYTES = 2_000_000
MAX_IMAGE_BYTES = 8_000_000
MAX_PDF_BYTES = 12_000_000
MAX_EXTRACTED_CHARS = 60_000


@dataclass(frozen=True)
class ProcessedAttachment:
    name: str
    media_type: str
    size_bytes: int
    content_hash: str
    kind: str
    extracted_text: str = ''
    image_base64: str = ''

    def metadata(self) -> dict:
        return {
            'name': self.name, 'media_type': self.media_type,
            'size_bytes': self.size_bytes, 'content_hash': self.content_hash,
            'kind': self.kind, 'text_chars': len(self.extracted_text),
        }


def _decode(data_base64: str, limit: int) -> bytes:
    if len(data_base64) > (limit * 4 // 3) + 16:
        raise ValueError('Attachment exceeds the allowed size')
    try:
        data = base64.b64decode(data_base64, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError('Attachment data is not valid base64') from error
    if len(data) > limit:
        raise ValueError('Attachment exceeds the allowed size')
    return data


def _validate_image(data: bytes, media_type: str):
    signatures = {
        'image/png': (b'\x89PNG\r\n\x1a\n',),
        'image/jpeg': (b'\xff\xd8\xff',),
        'image/webp': (b'RIFF',),
        'image/gif': (b'GIF87a', b'GIF89a'),
    }
    if not any(data.startswith(signature) for signature in signatures[media_type]):
        raise ValueError(f'Attachment content does not match {media_type}')
    if media_type == 'image/webp' and data[8:12] != b'WEBP':
        raise ValueError('Attachment content does not match image/webp')


def _extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise ValueError('PDF processing is unavailable; install project dependencies') from error
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise ValueError('Encrypted PDFs are not supported')
        text = '\n\n'.join((page.extract_text() or '') for page in reader.pages[:100])
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(f'PDF could not be processed: {type(error).__name__}') from error
    return text[:MAX_EXTRACTED_CHARS]


def process_attachment(name: str, media_type: str, data_base64: str) -> ProcessedAttachment:
    """Decode and validate one attachment without writing it to disk."""
    safe_name = Path(name).name
    if not safe_name or safe_name in {'.', '..'}:
        raise ValueError('Attachment name is invalid')
    media_type = media_type.lower().split(';', 1)[0].strip()
    if media_type in IMAGE_TYPES:
        data = _decode(data_base64, MAX_IMAGE_BYTES)
        _validate_image(data, media_type)
        kind = 'image'
        text = ''
        image = base64.b64encode(data).decode('ascii')
    elif media_type == PDF_TYPE:
        data = _decode(data_base64, MAX_PDF_BYTES)
        if not data.startswith(b'%PDF-'):
            raise ValueError('Attachment content does not match application/pdf')
        kind = 'pdf'
        text = _extract_pdf(data)
        image = ''
    elif media_type in TEXT_TYPES or media_type.startswith('text/'):
        data = _decode(data_base64, MAX_TEXT_BYTES)
        if b'\x00' in data:
            raise ValueError('Binary content cannot be processed as text')
        kind = 'text'
        text = data.decode('utf-8', errors='replace')[:MAX_EXTRACTED_CHARS]
        if media_type == 'application/json':
            try:
                json.loads(text)
            except json.JSONDecodeError as error:
                raise ValueError('JSON attachment is invalid') from error
        image = ''
    else:
        raise ValueError(f'Unsupported attachment type: {media_type or "unknown"}')
    return ProcessedAttachment(
        name=safe_name, media_type=media_type, size_bytes=len(data),
        content_hash=hashlib.sha256(data).hexdigest(), kind=kind,
        extracted_text=text, image_base64=image,
    )


def attachment_context(attachments: list[ProcessedAttachment]) -> str:
    parts = []
    for item in attachments:
        if item.extracted_text:
            parts.append(
                f'--- Attachment: {item.name} [{item.media_type}] ---\n{item.extracted_text}'
            )
    return '\n\n'.join(parts)
