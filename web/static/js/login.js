// login.js — Xử lý OAuth2 callback và 2FA verify
// Backend set cookie HttpOnly `2fa_pending` + redirect về `/?require_2fa=1`
// Frontend chỉ cần đọc query flag và gọi POST /auth/verify-2fa (cookie tự gửi)

const params = new URLSearchParams(window.location.search);
if (params.get("require_2fa") === "1") {
    const modal = document.getElementById("modal-2fa");
    if (window.HMUI && typeof window.HMUI.openModal === "function") {
        window.HMUI.openModal(modal);
    } else {
        modal.removeAttribute("hidden");
        modal.classList.remove("hidden");
    }
    // Auto-focus input để user gõ ngay
    setTimeout(() => document.getElementById("otp-input")?.focus(), 100);
    // Dọn URL — không lưu lại flag trong history
    window.history.replaceState({}, "", "/");
}

async function verify2FA() {
    const otp = document.getElementById("otp-input").value.trim();
    const errorEl = document.getElementById("otp-error");
    errorEl.classList.add("hidden");

    if (otp.length !== 6 || !/^\d+$/.test(otp)) {
        errorEl.textContent = "Mã OTP phải gồm 6 chữ số";
        errorEl.classList.remove("hidden");
        return;
    }

    try {
        const resp = await fetch("/auth/verify-2fa", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({ otp_code: otp }),  // temp_token đã có trong cookie
        });

        if (resp.ok) {
            window.location.href = "/dashboard";
        } else {
            const data = await resp.json().catch(() => ({}));
            errorEl.textContent = data.detail || "Mã OTP không đúng";
            errorEl.classList.remove("hidden");
        }
    } catch (e) {
        errorEl.textContent = "Lỗi kết nối. Vui lòng thử lại.";
        errorEl.classList.remove("hidden");
    }
}

// Cho phép nhấn Enter trong ô OTP
document.getElementById("otp-input")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") verify2FA();
});
