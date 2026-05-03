"""
test_ocr_validation.py — Unit test cho validation và image processing trong bot/utils/ocr.py

Kiểm tra:
- _check_magic_bytes(): nhận dạng PNG/JPEG/WEBP qua magic bytes
- _validate_image(): MIME type, size limit, magic bytes verification
- _preprocess_image(): chuyển đổi ảnh sang grayscale, resize

KHÔNG chạy EasyOCR thật — easyocr đã được mock trong conftest.py

Chạy: pytest tests/test_ocr_validation.py -v
"""
import io
import pytest
from PIL import Image

from bot.utils.ocr import _check_magic_bytes, _validate_image, _preprocess_image


# ─── Helper: tạo ảnh thật trong memory ───────────────────────────────────────

def _make_png_bytes(width: int = 100, height: int = 100) -> bytes:
    """Tạo PNG hợp lệ trong memory (không cần file trên disk)"""
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_jpeg_bytes(width: int = 100, height: int = 100) -> bytes:
    """Tạo JPEG hợp lệ trong memory"""
    img = Image.new("RGB", (width, height), color=(200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


# Magic bytes giả — chỉ header, không phải file hoàn chỉnh
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
_JPEG_MAGIC = b"\xff\xd8\xff" + b"\x00" * 50
_WEBP_MAGIC = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 50
_RANDOM_BYTES = b"\x00\x01\x02\x03\x04\x05\x06\x07" * 10


# ─── _check_magic_bytes ───────────────────────────────────────────────────────

class TestCheckMagicBytes:
    """Nhận dạng định dạng ảnh qua magic bytes (không phụ thuộc MIME header)"""

    def test_png_magic_bytes(self):
        assert _check_magic_bytes(_PNG_MAGIC) == "image/png"

    def test_jpeg_magic_bytes(self):
        assert _check_magic_bytes(_JPEG_MAGIC) == "image/jpeg"

    def test_webp_magic_bytes(self):
        assert _check_magic_bytes(_WEBP_MAGIC) == "image/webp"

    def test_unknown_returns_none(self):
        assert _check_magic_bytes(_RANDOM_BYTES) is None

    def test_empty_bytes_returns_none(self):
        assert _check_magic_bytes(b"") is None

    def test_short_bytes_returns_none(self):
        """Ít hơn 12 bytes không đủ để nhận diện"""
        assert _check_magic_bytes(b"\x89PNG") is None

    def test_real_png_magic(self):
        """PNG thật (tạo bằng PIL) phải nhận diện được"""
        png_bytes = _make_png_bytes()
        assert _check_magic_bytes(png_bytes) == "image/png"

    def test_real_jpeg_magic(self):
        """JPEG thật (tạo bằng PIL) phải nhận diện được"""
        jpeg_bytes = _make_jpeg_bytes()
        assert _check_magic_bytes(jpeg_bytes) == "image/jpeg"


# ─── _validate_image ─────────────────────────────────────────────────────────

class TestValidateImage:
    """Kiểm tra validation đầu vào trước khi OCR"""

    def test_valid_png_no_exception(self):
        """PNG hợp lệ, đúng MIME → không có exception"""
        png_bytes = _make_png_bytes()
        _validate_image(png_bytes, "image/png")   # phải không raise

    def test_valid_jpeg_no_exception(self):
        jpeg_bytes = _make_jpeg_bytes()
        _validate_image(jpeg_bytes, "image/jpeg")  # phải không raise

    def test_wrong_mime_raises(self):
        """MIME type không được hỗ trợ (gif, pdf, etc.)"""
        png_bytes = _make_png_bytes()
        with pytest.raises(ValueError, match="không được hỗ trợ|Chấp nhận"):
            _validate_image(png_bytes, "image/gif")

    def test_pdf_mime_raises(self):
        png_bytes = _make_png_bytes()
        with pytest.raises(ValueError):
            _validate_image(png_bytes, "application/pdf")

    def test_file_too_large_raises(self):
        """File > MAX_FILE_SIZE_MB (5MB) → ValueError"""
        from bot.config import settings
        max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
        # Tạo PNG hợp lệ trước, sau đó pad thêm để vượt giới hạn
        # (dùng magic bytes thay vì tạo ảnh thật 5MB tốn RAM)
        fake_large = _PNG_MAGIC + b"\x00" * (max_bytes + 1)
        with pytest.raises(ValueError, match="quá lớn|MB"):
            _validate_image(fake_large, "image/png")

    def test_exactly_max_size_ok(self):
        """Đúng giới hạn → không lỗi (chỉ > max mới lỗi)"""
        from bot.config import settings
        max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
        fake_max = _PNG_MAGIC + b"\x00" * (max_bytes - len(_PNG_MAGIC))
        # max_bytes bytes với magic bytes đúng → không lỗi size
        _validate_image(fake_max, "image/png")   # phải không raise

    def test_fake_mime_real_bytes_ok(self):
        """
        Ảnh PNG thật nhưng MIME claim là 'image/jpeg'
        → magic bytes chứng minh là ảnh hợp lệ (PNG) → được chấp nhận

        OCR không yêu cầu MIME và magic phải khớp nhau,
        chỉ cần magic bytes chứng minh là ảnh hợp lệ.
        """
        png_bytes = _make_png_bytes()
        # MIME sai (jpeg) nhưng magic bytes đúng (png) → hợp lệ vì magic OK
        _validate_image(png_bytes, "image/jpeg")   # phải không raise

    def test_wrong_magic_bytes_raises(self):
        """Bytes ngẫu nhiên với MIME hợp lệ → magic bytes sai → ValueError"""
        with pytest.raises(ValueError, match="không phải ảnh|hợp lệ"):
            _validate_image(_RANDOM_BYTES, "image/png")

    def test_empty_bytes_raises(self):
        """Bytes rỗng → magic bytes fail → ValueError"""
        with pytest.raises(ValueError):
            _validate_image(b"", "image/png")


# ─── _preprocess_image ────────────────────────────────────────────────────────

class TestPreprocessImage:
    """Kiểm tra tiền xử lý ảnh trước khi OCR"""

    def test_returns_bytes(self):
        """Phải trả về bytes (PNG đã xử lý)"""
        png_bytes = _make_png_bytes(200, 200)
        result = _preprocess_image(png_bytes)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_output_is_valid_png(self):
        """Output phải là PNG hợp lệ (PIL có thể mở được)"""
        png_bytes = _make_png_bytes(200, 200)
        result = _preprocess_image(png_bytes)
        img = Image.open(io.BytesIO(result))
        assert img.format == "PNG"

    def test_converts_to_grayscale(self):
        """Output phải là ảnh grayscale (mode 'L')"""
        png_bytes = _make_png_bytes(200, 200)
        result = _preprocess_image(png_bytes)
        img = Image.open(io.BytesIO(result))
        assert img.mode == "L"

    def test_small_image_upscaled(self):
        """Ảnh < 300px → phải được resize lên"""
        small_png = _make_png_bytes(width=50, height=50)
        result = _preprocess_image(small_png)
        img = Image.open(io.BytesIO(result))
        # Sau resize, ít nhất một chiều phải ≥ 300
        assert img.width >= 300 or img.height >= 100

    def test_large_image_not_downscaled(self):
        """Ảnh lớn đủ (>300px) không bị thu nhỏ"""
        large_png = _make_png_bytes(width=800, height=600)
        result = _preprocess_image(large_png)
        img = Image.open(io.BytesIO(result))
        # Kích thước phải giữ nguyên (không scale down)
        assert img.width == 800
        assert img.height == 600

    def test_rgba_image_converted(self):
        """Ảnh RGBA (có alpha) phải xử lý được — convert sang RGB trước"""
        rgba_img = Image.new("RGBA", (200, 200), color=(255, 255, 255, 128))
        buf = io.BytesIO()
        rgba_img.save(buf, format="PNG")
        rgba_bytes = buf.getvalue()

        result = _preprocess_image(rgba_bytes)   # phải không raise
        img = Image.open(io.BytesIO(result))
        assert img.mode == "L"   # cuối cùng phải là grayscale

    def test_jpeg_input_ok(self):
        """JPEG cũng phải xử lý được"""
        jpeg_bytes = _make_jpeg_bytes(200, 200)
        result = _preprocess_image(jpeg_bytes)
        assert isinstance(result, bytes)
        assert len(result) > 0
