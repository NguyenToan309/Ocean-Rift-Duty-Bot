"""
ocr.py — OCR pipeline: nhận ảnh bytes → trích xuất text → parse LOG DUTY
Dùng EasyOCR với ngôn ngữ Vietnamese + English
"""
import io
import logging
from functools import lru_cache

from PIL import Image
from bot.config import settings
from bot.utils.parser import ParsedDutyLog, parse_duty_text

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_reader():
    """
    Lazy-load EasyOCR reader (tốn ~500MB RAM, chỉ khởi tạo 1 lần).
    gpu=False vì VPS thường không có GPU.
    """
    import easyocr
    logger.info("Đang khởi tạo EasyOCR reader (lần đầu sẽ tải model)...")
    return easyocr.Reader(["vi", "en"], gpu=False)


def _check_magic_bytes(image_bytes: bytes) -> str | None:
    """
    Kiểm tra magic bytes để xác định loại ảnh thật sự (chống MIME spoofing).
    Trả về MIME type tương ứng hoặc None nếu không nhận diện được.
    """
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return None


def _validate_image(image_bytes: bytes, mime_type: str) -> None:
    """Kiểm tra MIME type, magic bytes và kích thước ảnh trước khi OCR"""
    if mime_type not in settings.ALLOWED_IMAGE_MIME:
        raise ValueError(
            f"Định dạng ảnh không được hỗ trợ: {mime_type}. "
            f"Chấp nhận: {', '.join(settings.ALLOWED_IMAGE_MIME)}"
        )
    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if len(image_bytes) > max_bytes:
        raise ValueError(f"Ảnh quá lớn. Tối đa {settings.MAX_FILE_SIZE_MB}MB")

    # Chống MIME spoofing — verify bằng magic bytes.
    # Discord có thể transcode ảnh (vd webp → png) nên chỉ cần là 1 trong các
    # định dạng ảnh hợp lệ, KHÔNG bắt buộc khớp chính xác MIME claimed.
    actual_mime = _check_magic_bytes(image_bytes)
    if actual_mime is None:
        raise ValueError("File không phải ảnh hợp lệ (PNG/JPEG/WEBP)")


def _preprocess_image(image_bytes: bytes) -> bytes:
    """
    Tiền xử lý ảnh để tăng độ chính xác OCR:
    - Chuyển sang grayscale
    - Resize nếu quá nhỏ (< 300px)
    - Tăng contrast nhẹ
    """
    img = Image.open(io.BytesIO(image_bytes))

    # Chuyển sang RGB trước để tránh lỗi với ảnh RGBA/P mode
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    # Grayscale giúp OCR nhận chữ tốt hơn
    img = img.convert("L")

    # Resize nếu ảnh quá nhỏ
    w, h = img.size
    if w < 300 or h < 100:
        scale = max(300 / w, 100 / h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def extract_duty_from_image(
    image_bytes: bytes,
    mime_type: str,
) -> ParsedDutyLog | None:
    """
    Pipeline đầy đủ:
    1. Validate MIME + size
    2. Tiền xử lý ảnh
    3. OCR → raw text
    4. Parse LOG DUTY
    5. Trả về ParsedDutyLog hoặc None

    Chạy sync OCR trong executor để không block event loop
    """
    import asyncio

    # Bước 1: Validate (sync, nhanh)
    _validate_image(image_bytes, mime_type)

    # Bước 2: Tiền xử lý
    processed_bytes = _preprocess_image(image_bytes)

    # Bước 3: OCR trong thread pool (EasyOCR không async)
    loop = asyncio.get_event_loop()
    raw_text = await loop.run_in_executor(None, _run_ocr, processed_bytes)

    if not raw_text:
        logger.warning("OCR không trích xuất được text từ ảnh")
        return None

    logger.info(f"OCR raw text ({len(raw_text)} chars):\n--- BEGIN OCR ---\n{raw_text}\n--- END OCR ---")

    # Bước 4: Parse
    result = parse_duty_text(raw_text)
    if result is None:
        logger.warning(f"Không tìm thấy LOG DUTY trong text OCR. Text trên đã log ở INFO level.")

    return result


def _run_ocr(image_bytes: bytes) -> str:
    """Chạy EasyOCR (blocking) — gọi trong executor"""
    reader = _get_reader()
    results = reader.readtext(image_bytes, detail=0, paragraph=True)
    return "\n".join(results)
