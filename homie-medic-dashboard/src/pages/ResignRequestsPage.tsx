import { DoorOpen, AlertTriangle } from 'lucide-react';
import { Card } from '../components/ui/card';
import { EmptyState } from '../components/shared/misc';

export function ResignRequestsPage() {
  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
          <DoorOpen className="h-6 w-6 text-[var(--warning)]" />
          Đơn xin ra khỏi ngành
        </h1>
        <p className="text-sm text-[var(--muted-foreground)] mt-1">
          Phê duyệt đơn xin thôi việc / rời ngành y tế
        </p>
      </div>

      <Card className="p-5 border-l-4 border-l-[var(--warning)] bg-[var(--warning)]/5">
        <div className="flex gap-3">
          <AlertTriangle className="h-5 w-5 text-[var(--warning)] shrink-0" />
          <div>
            <p className="font-semibold text-sm">Cảnh báo: Hành động không thể hoàn tác</p>
            <p className="text-xs text-[var(--muted-foreground)] mt-1">
              Duyệt đơn xin ra ngành sẽ <strong>gỡ vĩnh viễn Discord role y tế</strong> của nhân viên,
              xóa tất cả lịch trực, và đánh dấu inactive. Cẩn thận kiểm tra trước khi duyệt.
            </p>
          </div>
        </div>
      </Card>

      <Card className="p-8">
        <EmptyState
          icon={<DoorOpen className="h-12 w-12" />}
          title="Chưa có đơn xin ra ngành"
          description="Nhân viên gửi đơn bằng lệnh /xinoutnganh trong Discord. Hiện chưa có đơn nào chờ xử lý."
        />
      </Card>
    </div>
  );
}
