import { useState, useEffect } from 'react';
import {
  Stethoscope, Search, UserPlus, Pencil, Trash2, ChevronDown,
  Settings as SettingsIcon, AlertCircle, X, Users,
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { useStaffList } from '../hooks/useApi';
import { api, type StaffMember, type SystemRole, formatError } from '../lib/api';
import { promptNote } from '../lib/promptNote';
import { Card } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input, Textarea, Label } from '../components/ui/input';
import { NativeSelect } from '../components/ui/select';
import { Avatar } from '../components/ui/avatar';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from '../components/ui/dialog';
import { EmptyState, Skeleton, DiscordIdChip } from '../components/shared/misc';
import { avatarText } from '../lib/format';
import { useAvatars } from '../contexts/AvatarContext';
import { cn } from '../lib/cn';

const POSITIONS = [
  { code: 'VIEN_TRUONG', label: 'Viện Trưởng', group: 'LANH_DAO', color: 'var(--pos-vien-truong)' },
  { code: 'VIEN_PHO', label: 'Viện Phó', group: 'LANH_DAO', color: 'var(--pos-vien-pho)' },
  { code: 'THU_KY', label: 'Thư Ký', group: 'LANH_DAO', color: 'var(--pos-thu-ky)' },
  { code: 'QUAN_LY_BAC_SI', label: 'Quản Lý Bác Sĩ', group: 'LANH_DAO', color: 'var(--pos-qly-bac-si)' },
  { code: 'TRUONG_KHOA', label: 'Trưởng Khoa', group: 'Y_TE', color: 'var(--pos-truong-khoa)' },
  { code: 'PHO_KHOA', label: 'Phó Khoa', group: 'Y_TE', color: 'var(--pos-pho-khoa)' },
  { code: 'BAC_SI', label: 'Bác Sĩ', group: 'Y_TE', color: 'var(--pos-bac-si)' },
  { code: 'THUC_TAP_SINH', label: 'Thực Tập Sinh', group: 'DAO_TAO', color: 'var(--pos-thuc-tap-sinh)' },
];

const GROUPS = [
  { code: 'LANH_DAO', label: 'LÃNH ĐẠO', icon: '🏥', color: 'var(--destructive)' },
  { code: 'Y_TE', label: 'Y TẾ', icon: '🩺', color: 'var(--success)' },
  { code: 'DAO_TAO', label: 'ĐÀO TẠO', icon: '🎓', color: 'var(--muted-foreground)' },
];

export function StaffPage() {
  const { currentGuildId, currentGuild } = useAuth();
  const isAdmin = currentGuild?.is_admin || false;

  const [search, setSearch] = useState('');
  const [filterGroup, setFilterGroup] = useState<string>('');
  const [showInactive, setShowInactive] = useState(false);
  const [editing, setEditing] = useState<StaffMember | null>(null);
  const [adding, setAdding] = useState(false);

  const staffQ = useStaffList(currentGuildId, {
    group: filterGroup || undefined,
    is_active: showInactive ? undefined : true,
    search: search || undefined,
  });

  const stats = GROUPS.map(g => ({
    ...g,
    count: staffQ.data?.counts_by_group?.[g.code as keyof typeof staffQ.data.counts_by_group] || 0,
  }));

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Stethoscope className="h-6 w-6 text-[var(--primary)]" />
            Quản lý Nhân sự
          </h1>
          <p className="text-sm text-[var(--muted-foreground)] mt-1">
            Phân chức vụ y tế và tự động đồng bộ Discord role
          </p>
        </div>
        {isAdmin && (
          <Button onClick={() => setAdding(true)} size="lg">
            <UserPlus className="h-4 w-4" /> Thêm nhân sự
          </Button>
        )}
      </div>

      {/* Stats by group */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {stats.map(s => (
          <Card key={s.code} className="p-5 flex items-center justify-between hover:-translate-y-px transition-transform">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-[var(--muted-foreground)] mb-1">
                {s.icon} {s.label}
              </p>
              <p className="text-3xl font-bold" style={{ color: s.color }}>{s.count}</p>
              <p className="text-xs text-[var(--muted-foreground)]">nhân sự</p>
            </div>
            <div
              className="w-12 h-12 rounded-full flex items-center justify-center text-2xl"
              style={{ backgroundColor: `${s.color}20`, color: s.color }}
            >
              {s.icon}
            </div>
          </Card>
        ))}
      </div>

      {/* Filter bar */}
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[220px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--muted-foreground)]" />
            <Input
              placeholder="Tìm theo tên..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="pl-9"
            />
          </div>
          <NativeSelect
            value={filterGroup}
            onChange={e => setFilterGroup(e.target.value)}
            className="w-auto min-w-[180px]"
          >
            <option value="">— Tất cả nhóm —</option>
            <option value="LANH_DAO">🏥 Lãnh đạo</option>
            <option value="Y_TE">🩺 Y tế</option>
            <option value="DAO_TAO">🎓 Đào tạo</option>
          </NativeSelect>
          <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
            <input
              type="checkbox"
              checked={showInactive}
              onChange={e => setShowInactive(e.target.checked)}
              className="rounded accent-[var(--primary)]"
            />
            Hiện cả người đã nghỉ
          </label>
        </div>
      </Card>

      {/* Groups */}
      {staffQ.loading && (
        <div className="space-y-4">
          {[...Array(2)].map((_, i) => (
            <Card key={i} className="p-6">
              <Skeleton className="h-4 w-32 mb-4" />
              <div className="grid grid-cols-3 gap-3">
                {[...Array(3)].map((_, j) => <Skeleton key={j} className="h-24" />)}
              </div>
            </Card>
          ))}
        </div>
      )}

      {!staffQ.loading && (staffQ.data?.items || []).length === 0 && (
        <Card className="p-8">
          <EmptyState
            icon={<Users className="h-12 w-12" />}
            title="Chưa có nhân sự nào"
            description={isAdmin ? 'Bấm "Thêm nhân sự" hoặc dùng /nhansu add trong Discord.' : 'Admin chưa thêm nhân sự.'}
          />
        </Card>
      )}

      {!staffQ.loading && (staffQ.data?.items || []).length > 0 && (
        <div className="space-y-6">
          {GROUPS.map(group => {
            const groupItems = (staffQ.data?.items || []).filter(m => m.position_group === group.code);
            if (groupItems.length === 0) return null;
            return (
              <section key={group.code}>
                <div className="flex items-center gap-3 mb-3">
                  <div className="h-px flex-1" style={{ backgroundColor: `${group.color}40` }} />
                  <h2
                    className="text-xs font-bold uppercase tracking-widest px-3 py-1 rounded-full"
                    style={{ color: group.color, backgroundColor: `${group.color}15` }}
                  >
                    {group.icon} {group.label} · {groupItems.length}
                  </h2>
                  <div className="h-px flex-1" style={{ backgroundColor: `${group.color}40` }} />
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                  {groupItems.map(m => (
                    <StaffCard
                      key={m.id}
                      member={m}
                      canEdit={isAdmin}
                      onEdit={() => setEditing(m)}
                    />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      )}

      {/* Position role map config (Admin only) */}
      {isAdmin && <PositionRoleMapCard guildId={currentGuildId} />}

      {/* Edit/Add modal */}
      {(editing || adding) && (
        <StaffEditModal
          mode={adding ? 'add' : 'edit'}
          staff={editing}
          guildId={currentGuildId}
          onClose={() => { setEditing(null); setAdding(false); }}
          onSaved={() => { staffQ.refetch(); setEditing(null); setAdding(false); }}
        />
      )}
    </div>
  );
}

function StaffCard({ member, canEdit, onEdit }: { member: StaffMember; canEdit: boolean; onEdit: () => void }) {
  const meta = POSITIONS.find(p => p.code === member.position);
  const { getAvatar } = useAvatars();
  // Ưu tiên avatar_url từ staff API, fallback từ context cache
  const avatarUrl = member.avatar_url || getAvatar(member.user_id);
  return (
    <Card
      className={cn(
        'p-3 relative overflow-hidden transition-all hover:-translate-y-0.5 hover:shadow-md',
        !member.is_active && 'opacity-60 border-dashed',
      )}
    >
      <div
        className="absolute left-0 top-0 bottom-0 w-1"
        style={{ backgroundColor: meta?.color || 'var(--muted)' }}
      />
      <div className="flex items-start gap-3 pl-2">
        <Avatar
          src={avatarUrl}
          fallback={avatarText(member.username)}
          size={36}
          className="ring-2 shrink-0"
          style={{ '--tw-ring-color': meta?.color || 'var(--border)' } as any}
        />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-bold truncate flex items-center gap-1">
            <span>{member.position_icon}</span> {member.username}
          </p>
          <DiscordIdChip id={member.user_id} />
          <div className="flex items-center gap-1.5 mt-2 flex-wrap">
            <Badge
              variant="default"
              style={{
                backgroundColor: `${meta?.color || 'var(--muted)'}20`,
                color: meta?.color || 'var(--foreground)',
              }}
              className="border-0 text-[10px]"
            >
              {member.position_label}
            </Badge>
            {member.department && (
              <Badge variant="outline" className="text-[10px]">
                {member.department}
              </Badge>
            )}
            {!member.is_active && (
              <Badge variant="secondary" className="text-[10px]">Đã nghỉ</Badge>
            )}
          </div>
          {member.note && (
            <p className="text-xs text-[var(--muted-foreground)] italic mt-2 line-clamp-2">
              _{member.note}_
            </p>
          )}
        </div>
        {canEdit && (
          <button
            onClick={onEdit}
            className="p-1.5 hover:bg-[var(--muted)] rounded-md text-[var(--muted-foreground)] hover:text-[var(--primary)] transition-colors"
            aria-label="Sửa"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </Card>
  );
}

function StaffEditModal({
  mode,
  staff,
  guildId,
  onClose,
  onSaved,
}: {
  mode: 'add' | 'edit';
  staff: StaffMember | null;
  guildId: string | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    user_id: staff?.user_id || '',
    username: staff?.username || '',
    position: staff?.position || 'BAC_SI',
    department: staff?.department || '',
    joined_at: staff?.joined_at?.split('T')[0] || '',
    note: '',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!guildId) return;
    if (form.note.trim().length < 3) {
      setError('Bắt buộc ghi lý do (≥3 ký tự).');
      return;
    }
    if (mode === 'add') {
      if (!form.user_id || form.user_id.length < 15) {
        setError('Discord ID không hợp lệ (≥15 chữ số).');
        return;
      }
      if (!form.username.trim()) {
        setError('Tên hiển thị bắt buộc.');
        return;
      }
    }
    setSaving(true);
    setError(null);
    try {
      if (mode === 'add') {
        await api.staffAdd(guildId, {
          user_id: form.user_id,
          username: form.username.trim(),
          position: form.position,
          department: form.department.trim() || undefined,
          joined_at: form.joined_at || undefined,
          note: form.note.trim(),
        });
      } else {
        await api.staffUpdate(guildId, staff!.user_id, {
          position: form.position,
          department: form.department.trim() || null,
          joined_at: form.joined_at || null,
          note: form.note.trim(),
        });
      }
      onSaved();
    } catch (err) {
      setError(formatError(err));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!guildId || !staff) return;
    const note = await promptNote({
      title: `Gỡ ${staff.username} khỏi danh sách nhân sự?`,
      description: 'Nhân viên sẽ chuyển sang trạng thái không hoạt động (soft-delete). Có thể khôi phục sau.',
      placeholder: 'VD: nghỉ việc theo nguyện vọng, chuyển công tác...',
      minLength: 3,
      destructive: true,
      confirmLabel: 'Gỡ khỏi danh sách',
    });
    if (note === null) return;
    setSaving(true);
    try {
      await api.staffRemove(guildId, staff.user_id, note, false);
      onSaved();
    } catch (err) {
      setError(formatError(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open onOpenChange={open => !open && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <div className="flex items-center gap-3">
            {staff && (
              <Avatar
                src={staff.avatar_url || ''}
                fallback={avatarText(staff.username)}
                size={36}
              />
            )}
            <div>
              <DialogTitle>{mode === 'add' ? 'Thêm nhân sự mới' : staff?.username || 'Cập nhật nhân sự'}</DialogTitle>
              {staff && (
                <DialogDescription className="font-mono-id text-[10px]">
                  ID: {staff.user_id}
                </DialogDescription>
              )}
            </div>
          </div>
        </DialogHeader>

        <div className="space-y-4 max-h-[60vh] overflow-y-auto pr-1">
          {mode === 'add' && (
            <>
              <div>
                <Label required>Discord User ID</Label>
                <Input
                  inputMode="numeric"
                  placeholder="VD: 1119880453671899196"
                  value={form.user_id}
                  onChange={e => setForm({ ...form, user_id: e.target.value.replace(/\D/g, '') })}
                  className="font-mono-id mt-1"
                />
              </div>
              <div>
                <Label required>Tên hiển thị</Label>
                <Input
                  placeholder="VD: BS. Nguyễn Văn A"
                  value={form.username}
                  onChange={e => setForm({ ...form, username: e.target.value })}
                  className="mt-1"
                />
              </div>
            </>
          )}

          <div>
            <Label required>Chức vụ</Label>
            <NativeSelect
              value={form.position}
              onChange={e => setForm({ ...form, position: e.target.value })}
              className="mt-1"
            >
              <optgroup label="🏥 LÃNH ĐẠO">
                <option value="VIEN_TRUONG">🏥 Viện Trưởng</option>
                <option value="VIEN_PHO">🏥 Viện Phó</option>
                <option value="THU_KY">📋 Thư Ký</option>
                <option value="QUAN_LY_BAC_SI">👨‍⚕️ Quản Lý Bác Sĩ</option>
              </optgroup>
              <optgroup label="🩺 Y TẾ">
                <option value="TRUONG_KHOA">🩺 Trưởng Khoa</option>
                <option value="PHO_KHOA">🩺 Phó Khoa</option>
                <option value="BAC_SI">👨‍⚕️ Bác Sĩ</option>
              </optgroup>
              <optgroup label="🎓 ĐÀO TẠO">
                <option value="THUC_TAP_SINH">🎓 Thực Tập Sinh</option>
              </optgroup>
            </NativeSelect>
          </div>

          <div>
            <Label>Khoa / Phòng ban</Label>
            <Input
              placeholder="VD: Khoa Nội, Khoa Cấp cứu"
              value={form.department}
              onChange={e => setForm({ ...form, department: e.target.value })}
              className="mt-1"
            />
          </div>

          <div>
            <Label>Ngày vào làm</Label>
            <Input
              type="date"
              value={form.joined_at}
              onChange={e => setForm({ ...form, joined_at: e.target.value })}
              className="mt-1"
            />
          </div>

          <div>
            <Label required>Lý do thay đổi</Label>
            <Textarea
              rows={3}
              placeholder={mode === 'add' ? 'VD: Thêm nhân sự mới, đã ký HĐ ngày...' : 'VD: Bổ nhiệm chức vụ mới từ ngày...'}
              value={form.note}
              onChange={e => setForm({ ...form, note: e.target.value })}
              className="mt-1"
            />
            <p className="text-[10px] text-[var(--muted-foreground)] mt-1">
              Mọi thay đổi được ghi audit log với lý do này (bắt buộc ≥3 ký tự).
            </p>
          </div>

          {error && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-[var(--destructive)]/10 text-[var(--destructive)] text-sm">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}
        </div>

        <DialogFooter className="justify-between sm:justify-between">
          {mode === 'edit' && staff && (
            <Button variant="destructive" onClick={remove} disabled={saving}>
              <Trash2 className="h-4 w-4" /> Gỡ khỏi DS
            </Button>
          )}
          <div className="flex gap-2 ml-auto">
            <Button variant="outline" onClick={onClose} disabled={saving}>Hủy</Button>
            <Button onClick={submit} disabled={saving}>
              {saving ? 'Đang lưu...' : mode === 'add' ? 'Thêm nhân sự' : 'Lưu thay đổi'}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PositionRoleMapCard({ guildId }: { guildId: string | null }) {
  const [expanded, setExpanded] = useState(false);
  const [draft, setDraft] = useState<Record<string, SystemRole | ''>>({});
  const [original, setOriginal] = useState<Record<string, SystemRole>>({});
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<Date | null>(null);

  useEffect(() => {
    if (!guildId || !expanded) return;
    api.staffGetPositionRoleMap(guildId)
      .then(r => {
        setOriginal(r.position_role_map || {});
        setDraft(r.position_role_map || {});
      })
      .catch(console.warn);
  }, [guildId, expanded]);

  const dirty = JSON.stringify(draft) !== JSON.stringify(original);

  const save = async () => {
    if (!guildId) return;
    const note = await promptNote({
      title: 'Cập nhật map chức vụ → quyền',
      description: 'Nhập lý do thay đổi để ghi audit log. Tối thiểu 3 ký tự.',
      placeholder: 'VD: tái cơ cấu phòng ban, mở rộng quyền cho khoa nội...',
      minLength: 3,
    });
    if (note === null) return;
    setSaving(true);
    try {
      const r = await api.staffUpdatePositionRoleMap(guildId, draft as any, note);
      setOriginal(r.position_role_map);
      setSavedAt(new Date());
    } catch (err) {
      alert('Lỗi: ' + formatError(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="overflow-hidden">
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full px-5 py-4 flex items-center justify-between hover:bg-[var(--muted)]/50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-[var(--primary)]/10 text-[var(--primary)] flex items-center justify-center">
            <SettingsIcon className="h-4 w-4" />
          </div>
          <div className="text-left">
            <p className="font-semibold text-sm">Cấu hình Auto-Sync Discord Role</p>
            <p className="text-xs text-[var(--muted-foreground)]">Map chức vụ y tế → quyền hệ thống → Discord role</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {dirty && <Badge variant="warning">Chưa lưu</Badge>}
          <ChevronDown className={cn('h-4 w-4 transition-transform text-[var(--muted-foreground)]', expanded && 'rotate-180')} />
        </div>
      </button>

      {expanded && (
        <div className="px-5 pb-5 border-t border-[var(--border)] space-y-4">
          <div className="flex items-start gap-2 p-3 rounded-lg bg-[var(--warning)]/10 text-[var(--warning-foreground)] mt-4">
            <AlertCircle className="h-4 w-4 text-[var(--warning)] shrink-0 mt-0.5" />
            <p className="text-xs text-[var(--warning)]">
              <strong>Lưu ý:</strong> Khi bật, đổi chức vụ sẽ TỰ ĐỘNG cấp/gỡ Discord role tương ứng.
              Bot Discord role phải <strong>CAO HƠN</strong> các role được map, nếu không sẽ báo 403.
            </p>
          </div>

          {POSITIONS.map(p => (
            <div
              key={p.code}
              className="flex items-center justify-between gap-3 py-2 border-b border-[var(--border)]/50 last:border-0"
            >
              <div className="flex items-center gap-2 flex-1">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: p.color }}
                />
                <div>
                  <p className="text-sm font-medium">{p.label}</p>
                  <p className="text-[10px] text-[var(--muted-foreground)]">{p.group}</p>
                </div>
              </div>
              <span className="text-[var(--muted-foreground)]">→</span>
              <NativeSelect
                value={draft[p.code] || ''}
                onChange={e => {
                  const v = e.target.value as SystemRole | '';
                  const next = { ...draft };
                  if (v) next[p.code] = v;
                  else delete next[p.code];
                  setDraft(next);
                }}
                className="w-[160px]"
              >
                <option value="">— Không map —</option>
                <option value="DUTY_ADMIN">DUTY_ADMIN</option>
                <option value="DUTY_MOD">DUTY_MOD</option>
                <option value="DUTY_MEMBER">DUTY_MEMBER</option>
              </NativeSelect>
            </div>
          ))}

          <div className="flex justify-between items-center pt-3">
            <p className="text-xs text-[var(--muted-foreground)]">
              {savedAt && `Đã lưu lúc ${savedAt.toLocaleTimeString('vi-VN')}`}
            </p>
            <Button onClick={save} disabled={!dirty || saving}>
              {saving ? 'Đang lưu...' : dirty ? 'Lưu thay đổi' : 'Đã đồng bộ'}
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
