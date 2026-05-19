import { Link } from 'react-router-dom';
import { Home, ArrowLeft, ServerCrash, Lock, FileQuestion } from 'lucide-react';
import { Button } from '../components/ui/button';

function ErrorShell({
  code, icon, title, description, primary,
}: {
  code: string;
  icon: React.ReactNode;
  title: string;
  description: string;
  primary?: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-[var(--background)] flex items-center justify-center p-6">
      <div className="max-w-md text-center">
        <div className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-[var(--muted)] mb-6">
          {icon}
        </div>
        <p className="text-6xl font-bold tracking-tight text-[var(--muted-foreground)] mb-2">{code}</p>
        <h1 className="text-2xl font-bold mb-2">{title}</h1>
        <p className="text-sm text-[var(--muted-foreground)] mb-6">{description}</p>
        {primary || (
          <Button asChild>
            <Link to="/">
              <Home className="h-4 w-4" /> Quay về Tổng quan
            </Link>
          </Button>
        )}
      </div>
    </div>
  );
}

export function NotFoundPage() {
  return (
    <ErrorShell
      code="404"
      icon={<FileQuestion className="h-10 w-10 text-[var(--muted-foreground)]" />}
      title="Không tìm thấy trang này"
      description="Trang bạn truy cập không tồn tại hoặc đã bị xóa. Hãy quay về Tổng quan để bắt đầu lại."
    />
  );
}

export function ForbiddenPage() {
  return (
    <ErrorShell
      code="403"
      icon={<Lock className="h-10 w-10 text-[var(--warning)]" />}
      title="Bạn không có quyền truy cập"
      description="Trang này yêu cầu quyền cao hơn (DUTY_ADMIN hoặc DUTY_MOD). Liên hệ Viện Trưởng để được cấp quyền."
      primary={
        <div className="flex gap-2 justify-center">
          <Button asChild variant="outline">
            <Link to="/"><ArrowLeft className="h-4 w-4" /> Quay lại</Link>
          </Button>
          <Button asChild>
            <Link to="/"><Home className="h-4 w-4" /> Tổng quan</Link>
          </Button>
        </div>
      }
    />
  );
}

export function ServerErrorPage() {
  return (
    <ErrorShell
      code="500"
      icon={<ServerCrash className="h-10 w-10 text-[var(--destructive)]" />}
      title="Lỗi máy chủ"
      description="Đã có lỗi xảy ra phía server. Vui lòng thử lại sau hoặc liên hệ kỹ thuật."
      primary={
        <div className="flex gap-2 justify-center">
          <Button onClick={() => window.location.reload()} variant="outline">
            Thử lại
          </Button>
          <Button asChild>
            <Link to="/"><Home className="h-4 w-4" /> Tổng quan</Link>
          </Button>
        </div>
      }
    />
  );
}
