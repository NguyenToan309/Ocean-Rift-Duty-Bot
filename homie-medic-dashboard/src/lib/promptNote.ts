/**
 * promptNote.ts — Imperative API thay thế window.prompt() bằng modal đẹp.
 *
 * Singleton pattern: <PromptNoteHost /> mount 1 lần ở RootLayout, expose ref
 * setter qua module global. Caller gọi `await promptNote({...})` ở bất kỳ đâu
 * (event handler, useEffect, async function) → modal mở → resolve khi user
 * confirm hoặc cancel.
 *
 * Sử dụng:
 *   const note = await promptNote({
 *     title: 'Lý do cập nhật map chức vụ',
 *     description: 'Tối thiểu 3 ký tự để ghi audit log.',
 *     minLength: 3,
 *     placeholder: 'VD: đổi sau khi họp ban...',
 *   });
 *   if (note === null) return;  // user cancel
 *   // note đảm bảo length >= minLength sau resolve
 */

export interface PromptNoteOptions {
  title: string;
  description?: string;
  placeholder?: string;
  minLength?: number;       // default 3
  maxLength?: number;       // default 500
  multiline?: boolean;      // default true (textarea)
  confirmLabel?: string;    // default "Xác nhận"
  cancelLabel?: string;     // default "Huỷ"
  destructive?: boolean;    // nếu true, nút confirm màu đỏ
}

export interface PromptNoteRequest extends PromptNoteOptions {
  resolve: (value: string | null) => void;
}

type Setter = (req: PromptNoteRequest | null) => void;

let _setter: Setter | null = null;

/**
 * Internal — PromptNoteHost gọi khi mount để đăng ký bộ điều khiển.
 * KHÔNG dùng trực tiếp ngoài host component.
 */
export function _registerPromptNoteSetter(setter: Setter | null): void {
  _setter = setter;
}

/**
 * Public API — mở dialog yêu cầu nhập note, trả về Promise<string | null>.
 * - resolve(string) khi user confirm + nhập đủ minLength
 * - resolve(null) khi user cancel hoặc đóng dialog
 *
 * Nếu PromptNoteHost chưa mount → console.warn + fallback window.prompt
 * để không break flow.
 */
export function promptNote(opts: PromptNoteOptions): Promise<string | null> {
  if (!_setter) {
    console.warn('[promptNote] PromptNoteHost chưa mount — fallback window.prompt');
    const v = window.prompt(opts.title);
    if (!v || v.trim().length < (opts.minLength ?? 3)) return Promise.resolve(null);
    return Promise.resolve(v.trim());
  }
  return new Promise((resolve) => {
    _setter!({ ...opts, resolve });
  });
}
