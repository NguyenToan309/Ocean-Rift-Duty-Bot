// login.js — Xử lý OAuth2 callback và 2FA verify

let tempToken = null;

// Kiểm tra URL params sau khi OAuth callback
const params = new URLSearchParams(window.location.search);
if (params.get("require_2fa") === "true") {
    tempToken = params.get("temp_token");
    document.getElementById("modal-2fa").classList.remove("hidden");
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
            body: JSON.stringify({ temp_token: tempToken, otp_code: otp }),
        });

        if (resp.ok) {
            window.location.href = "/dashboard";
        } else {
            const data = await resp.json();
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
