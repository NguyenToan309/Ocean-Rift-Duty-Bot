/**
 * PromptNoteHost.tsx — Modal dialog thay thế window.prompt() trong toàn app.
 * Mount 1 lần ở RootLayout, expose ref qua promptNote.ts singleton.
 *
 * Tính năng:
 * - Validation realtime: chữ đỏ + button disabled khi < minLength
 * - Textarea multiline (default) hoặc input 1 dòng
 * - Hỗ trợ Esc để cancel, Ctrl+Enter để confirm
 * - destructive flag → button confirm màu đỏ (vd: xoá log)
 */
import { useEffect, useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '../ui/dialog';
import { Button } from '../ui/button';
import { Textarea, Input } from '../ui/input';
import { _registerPromptNoteSetter, type PromptNoteRequest } from '../../lib/promptNote';
import { AlertCircle } from 'lucide-react';

export function PromptNoteHost() {
  const [req, setReq] = useState<PromptNoteRequest | null>(null);
  const [value, setValue] = useState('');

  useEffect(() => {
    _registerPromptNoteSetter(setReq);
    return () => _registerPromptNoteSetter(null);
  }, []);

  // Reset input mỗi lần dialog mở
  useEffect(() => {
    if (req) setValue('');
  }, [req]);

  if (!req) return null;

  const minLength = req.minLength ?? 3;
  const maxLength = req.maxLength ?? 500;
  const trimmed = value.trim();
  const tooShort = trimmed.length < minLength;
  const tooLong = trimmed.length > maxLength;
  const valid = !tooShort && !tooLong;
  const confirmLabel = req.confirmLabel ?? 'Xác nhận';
  const cancelLabel = req.cancelLabel ?? 'Huỷ';
  const multiline = req.multiline !== false;

  const finish = (result: string | null) => {
    req.resolve(result);
    setReq(null);
  };

  const onConfirm = () => {
    if (!valid) return;
    finish(trimmed);
  };

  const onCancel = () => finish(null);

  const onKey = (e: React.KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      onConfirm();
    }
  };

  return (
    <Dialog
      open={true}
      onOpenChange={(open) => {
        if (!open) onCancel();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{req.title}</DialogTitle>
          {req.description && <DialogDescription>{req.description}</DialogDescription>}
        </DialogHeader>

        <div className="space-y-2">
          {multiline ? (
            <Textarea
              autoFocus
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={onKey}
              placeholder={req.placeholder ?? `Tối thiểu ${minLength} ký tự...`}
              rows={4}
              maxLength={maxLength + 50}
              className="resize-none"
            />
          ) : (
            <Input
              autoFocus
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={onKey}
              placeholder={req.placeholder ?? `Tối thiểu ${minLength} ký tự...`}
              maxLength={maxLength + 50}
            />
          )}

          <div className="flex items-center justify-between text-xs">
            <div>
              {tooShort && trimmed.length > 0 && (
                <span className="flex items-center gap-1 text-[var(--destructive)]">
                  <AlertCircle className="h-3 w-3" />
                  Cần ít nhất {minLength} ký tự (hiện {trimmed.length})
                </span>
              )}
              {tooLong && (
                <span className="flex items-center gap-1 text-[var(--destructive)]">
                  <AlertCircle className="h-3 w-3" />
                  Vượt {maxLength} ký tự
                </span>
              )}
              {!tooShort && !tooLong && trimmed.length > 0 && (
                <span className="text-[var(--muted-foreground)]">✓ Hợp lệ</span>
              )}
              {trimmed.length === 0 && (
                <span className="text-[var(--muted-foreground)]">Nhập tối thiểu {minLength} ký tự để xác nhận</span>
              )}
            </div>
            <span className="text-[var(--muted-foreground)]">{trimmed.length} / {maxLength}</span>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            {cancelLabel}
          </Button>
          <Button
            variant={req.destructive ? 'destructive' : 'default'}
            onClick={onConfirm}
            disabled={!valid}
          >
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
