import { useState, useEffect } from 'react';
import {
  Settings as SettingsIcon, Save, Shield, Hash, Bell, Plug, Lock, Users, AlertCircle,
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { api, type SystemRole, formatError } from '../lib/api';
import { promptNote } from '../lib/promptNote';
import { useBranding } from '../contexts/BrandingContext';
import { Card } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input, Textarea, Label } from '../components/ui/input';
import { NativeSelect } from '../components/ui/select';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../components/ui/tabs';
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

export function SettingsPage() {
  const { currentGuildId, currentGuild, me } = useAuth();
  const isAdmin = currentGuild?.is_admin || false;
  const isBotOwner = me?.is_bot_owner || false;

  if (!isAdmin) {
    return (
      <Card className="p-8 max-w-md mx-auto text-center">
        <Lock className="h-12 w-12 mx-auto text-[var(--muted-foreground)] mb-3" />
        <h2 className="font-semibold mb-1">Yêu cầu quyền Admin</h2>
        <p className="text-sm text-[var(--muted-foreground)]">
          Chỉ tài khoản DUTY_ADMIN mới truy cập được trang Cài đặt.
        </p>
      </Card>
    );
  }

  return (
    <div className="space-y-6 max-w-6xl mx-auto pb-24">
      <div>
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
          <SettingsIcon className="h-6 w-6 text-[var(--primary)]" />
          Cài đặt hệ thống
        </h1>
        <p className="text-sm text-[var(--muted-foreground)] mt-1">
          Cấu hình toàn cục cho Discord Bot và dashboard
        </p>
      </div>

      <Tabs defaultValue="general">
        <TabsList className="w-full justify-start overflow-x-auto">
          <TabsTrigger value="general">
            <SettingsIcon className="h-3.5 w-3.5" /> Chung
          </TabsTrigger>
          <TabsTrigger value="roles">
            <Shield className="h-3.5 w-3.5" /> Vai trò
          </TabsTrigger>
          <TabsTrigger value="positions">
            <Users className="h-3.5 w-3.5" /> Chức vụ → Quyền
          </TabsTrigger>
          <TabsTrigger value="channels">
            <Hash className="h-3.5 w-3.5" /> Kênh Discord
          </TabsTrigger>
          <TabsTrigger value="notifications">
            <Bell className="h-3.5 w-3.5" /> Thông báo
          </TabsTrigger>
          <TabsTrigger value="integrations">
            <Plug className="h-3.5 w-3.5" /> Tích hợp
          </TabsTrigger>
          <TabsTrigger value="security">
            <Lock className="h-3.5 w-3.5" /> Bảo mật
          </TabsTrigger>
        </TabsList>

        <TabsContent value="general">
          <GeneralTab isBotOwner={isBotOwner} />
        </TabsContent>

        <TabsContent value="roles">
          <RoleMapTab guildId={currentGuildId} guildName={currentGuild?.name || ''} />
        </TabsContent>

        <TabsContent value="positions">
          <PositionRoleTab guildId={currentGuildId} />
        </TabsContent>

        <TabsContent value="channels">
          <Card className="p-6 max-w-2xl space-y-4">
            {[
              { key: 'log_channel_id', label: 'Kênh chấm công', icon: '📋' },
              { key: 'schedule_channel_id', label: 'Kênh đăng ký lịch', icon: '📅' },
              { key: 'remind_channel_id', label: 'Kênh nhắc trực', icon: '🔔' },
              { key: 'leave_channel_id', label: 'Kênh đơn nghỉ', icon: '🏖️' },
              { key: 'staff_channel_id', label: 'Kênh staff', icon: '👥' },
            ].map(c => (
              <div key={c.key}>
                <Label>{c.icon} {c.label}</Label>
                <Input placeholder="Channel ID (snowflake)" className="font-mono-id mt-1" />
              </div>
            ))}
          </Card>
        </TabsContent>

        <TabsContent value="notifications">
          <NotificationsTab guildId={currentGuildId} />
        </TabsContent>

        <TabsContent value="integrations">
          <Card className="p-6 max-w-2xl space-y-4">
            <div className="p-4 rounded-lg bg-[var(--success)]/5 border border-[var(--success)]/20">
              <div className="flex items-center gap-2 mb-1">
                <span className="h-2 w-2 rounded-full bg-[var(--success)] animate-pulse" />
                <p className="font-semibold text-[var(--success)]">✅ Discord Bot đang chạy</p>
              </div>
              <p className="text-xs text-[var(--muted-foreground)]">
                Bot ID: 1498049415355830437 · 10 cogs loaded · 30+ slash commands
              </p>
            </div>
            <div>
              <Label>Webhook đầu ra (Telegram / Zalo / Email)</Label>
              <Input placeholder="https://..." className="mt-1" />
              <p className="text-[10px] text-[var(--muted-foreground)] mt-1">
                Sẽ gửi notification ra dịch vụ ngoài. Sắp phát triển.
              </p>
            </div>
            <div>
              <Label>API Token quản lý</Label>
              <Button variant="outline" className="w-full mt-1">+ Tạo token mới</Button>
            </div>
          </Card>
        </TabsContent>

        <TabsContent value="security">
          <Card className="p-6 max-w-2xl space-y-4">
            <div>
              <Label>Xác thực 2 bước (2FA TOTP)</Label>
              <Button variant="outline" className="w-full mt-1">
                <Shield className="h-4 w-4" /> Setup Google Authenticator
              </Button>
            </div>
            <div>
              <Label>Session đang active</Label>
              <div className="space-y-1 mt-1">
                <div className="flex items-center justify-between p-3 rounded-lg border border-[var(--border)]">
                  <div>
                    <p className="text-sm font-medium">Chrome trên Windows · 192.168.1.100</p>
                    <p className="text-xs text-[var(--muted-foreground)]">Hôm nay 14:30 (session hiện tại)</p>
                  </div>
                  <Badge variant="success" className="text-[10px]">Active</Badge>
                </div>
              </div>
              <Button variant="destructive" className="w-full mt-2">Đăng xuất tất cả thiết bị</Button>
            </div>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function PositionRoleTab({ guildId }: { guildId: string | null }) {
  const [draft, setDraft] = useState<Record<string, SystemRole | ''>>({});
  const [original, setOriginal] = useState<Record<string, SystemRole>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Discord role name map — fetch theo guild để dropdown hiển thị
  // "DUTY_ADMIN — Cốc Chủ Thần Y" thay vì abstract "DUTY_ADMIN" thuần.
  const [roleNames, setRoleNames] = useState<Record<string, string | null>>({});

  useEffect(() => {
    if (!guildId) {
      // Reset state khi user logout hoặc chưa pick guild để tránh leak data guild cũ
      setDraft({});
      setOriginal({});
      setRoleNames({});
      return;
    }
    api.staffGetPositionRoleMap(guildId)
      .then(r => {
        setOriginal(r.position_role_map || {});
        setDraft(r.position_role_map || {});
      })
      .catch(console.warn);
    api.setupGetRoles(guildId)
      .then(r => {
        const m: Record<string, string | null> = {};
        for (const k of ['DUTY_ADMIN', 'DUTY_MOD', 'DUTY_MEMBER'] as const) {
          m[k] = r.role_map[k]?.role_name ?? null;
        }
        setRoleNames(m);
      })
      .catch(console.warn);
  }, [guildId]);

  const sysRoleLabel = (sys: 'DUTY_ADMIN' | 'DUTY_MOD' | 'DUTY_MEMBER') => {
    const name = roleNames[sys];
    return name ? `${sys} — ${name}` : sys;
  };

  const dirty = JSON.stringify(draft) !== JSON.stringify(original);

  const save = async () => {
    if (!guildId) return;
    const note = await promptNote({
      title: 'Cập nhật map chức vụ → quyền hệ thống',
      description: 'Nhập lý do thay đổi để ghi audit log. Tối thiểu 3 ký tự.',
      placeholder: 'VD: tổ chức tái cơ cấu phòng ban, đổi role sau cuộc họp ban...',
      minLength: 3,
    });
    if (note === null) return;
    setSaving(true);
    setError(null);
    try {
      const r = await api.staffUpdatePositionRoleMap(guildId, draft as any, note);
      setOriginal(r.position_role_map);
    } catch (err) {
      setError(formatError(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="p-6 max-w-3xl">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="font-semibold">Map Chức vụ Y tế → Quyền hệ thống</h3>
          <p className="text-sm text-[var(--muted-foreground)] mt-1">
            Khi đổi chức vụ nhân sự, bot tự động cấp/gỡ Discord role tương ứng.
          </p>
        </div>
      </div>

      <div className="p-3 rounded-lg bg-[var(--warning)]/10 border border-[var(--warning)]/20 mb-4 flex items-start gap-2">
        <AlertCircle className="h-4 w-4 text-[var(--warning)] shrink-0 mt-0.5" />
        <p className="text-xs text-[var(--warning)]">
          <strong>Lưu ý:</strong> Bot Discord role phải <strong>CAO HƠN</strong> các role được map, nếu không sẽ báo 403 (Bot không có quyền).
        </p>
      </div>

      <div className="space-y-2">
        {POSITIONS.map(p => (
          <div key={p.code} className="flex items-center gap-3 py-2 border-b border-[var(--border)] last:border-0">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: p.color }} />
            <div className="flex-1">
              <p className="text-sm font-medium">{p.label}</p>
              <p className="text-[10px] text-[var(--muted-foreground)]">{p.group}</p>
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
              <option value="DUTY_ADMIN">{sysRoleLabel('DUTY_ADMIN')}</option>
              <option value="DUTY_MOD">{sysRoleLabel('DUTY_MOD')}</option>
              <option value="DUTY_MEMBER">{sysRoleLabel('DUTY_MEMBER')}</option>
            </NativeSelect>
          </div>
        ))}
      </div>

      {error && (
        <div className="mt-3 flex items-start gap-2 p-3 rounded-lg bg-[var(--destructive)]/10 text-[var(--destructive)] text-sm">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
          {error}
        </div>
      )}

      <Button onClick={save} disabled={!dirty || saving} className="mt-4 w-full">
        <Save className="h-4 w-4" />
        {saving ? 'Đang lưu...' : dirty ? 'Lưu thay đổi' : 'Đã đồng bộ'}
      </Button>

      {/* Floating save bar */}
      {dirty && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 bg-[var(--card)] border border-[var(--border)] rounded-full shadow-xl px-5 py-2 flex items-center gap-3 z-30">
          <p className="text-sm">
            <span className="text-[var(--warning)]">●</span> Bạn có thay đổi chưa lưu
          </p>
          <Button size="sm" onClick={save} disabled={saving}>
            <Save className="h-3.5 w-3.5" /> Lưu ngay
          </Button>
        </div>
      )}
    </Card>
  );
}

// ─── General Tab (Chung) — đổi system_name + bot_activity_text ──────────────

function GeneralTab({ isBotOwner }: { isBotOwner: boolean }) {
  const { refresh: refreshBranding } = useBranding();
  const [systemName, setSystemName] = useState('');
  const [botActivity, setBotActivity] = useState('');
  const [originalName, setOriginalName] = useState('');
  const [originalActivity, setOriginalActivity] = useState('');
  const [maxName, setMaxName] = useState(60);
  const [maxActivity, setMaxActivity] = useState(128);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<Date | null>(null);

  useEffect(() => {
    if (!isBotOwner) {
      setLoading(false);
      return;
    }
    api.systemSettingsGet()
      .then(r => {
        const sn = r.settings.system_name;
        const ba = r.settings.bot_activity_text;
        setSystemName(sn.value);
        setOriginalName(sn.value);
        setBotActivity(ba.value);
        setOriginalActivity(ba.value);
        if (sn.max_length) setMaxName(sn.max_length);
        if (ba.max_length) setMaxActivity(ba.max_length);
      })
      .catch(err => setError(formatError(err)))
      .finally(() => setLoading(false));
  }, [isBotOwner]);

  const nameDirty = systemName.trim() !== originalName;
  const activityDirty = botActivity.trim() !== originalActivity;
  const dirty = nameDirty || activityDirty;
  const nameTooLong = systemName.trim().length > maxName;
  const activityTooLong = botActivity.trim().length > maxActivity;
  const nameEmpty = systemName.trim().length === 0;
  const activityEmpty = botActivity.trim().length === 0;
  const canSave = dirty && !nameTooLong && !activityTooLong && !nameEmpty && !activityEmpty;

  const save = async () => {
    if (!canSave) return;
    const note = await promptNote({
      title: 'Cập nhật branding hệ thống',
      description:
        'Đổi tên web hoặc text Discord presence. Bot sẽ áp dụng presence mới trong vòng 60 giây. ' +
        'Tối thiểu 3 ký tự để ghi audit log.',
      placeholder: 'VD: đổi brand sang Capy Medic theo yêu cầu...',
      minLength: 3,
    });
    if (note === null) return;
    setSaving(true);
    setError(null);
    try {
      const updates: Record<string, string> = {};
      if (nameDirty) updates.system_name = systemName.trim();
      if (activityDirty) updates.bot_activity_text = botActivity.trim();
      await api.systemSettingsUpdate(updates, note);
      setOriginalName(systemName.trim());
      setOriginalActivity(botActivity.trim());
      setSavedAt(new Date());
      // Reload branding context để Sidebar + title cập nhật ngay
      await refreshBranding();
    } catch (err) {
      setError(formatError(err));
    } finally {
      setSaving(false);
    }
  };

  if (!isBotOwner) {
    return (
      <Card className="p-6 max-w-2xl">
        <div className="flex items-start gap-2 p-3 rounded-lg bg-[var(--info)]/10 text-sm">
          <Lock className="h-4 w-4 mt-0.5 shrink-0" />
          <div>
            <p className="font-medium">Cần quyền Bot Owner</p>
            <p className="text-xs text-[var(--muted-foreground)] mt-1">
              Chỉ user trong env <code className="bg-[var(--muted)] px-1 rounded">BOT_OWNER_IDS</code> mới đổi
              được tên hệ thống và Discord presence của bot.
            </p>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card className="p-6 max-w-2xl space-y-5">
      <div>
        <h3 className="font-semibold mb-1">Branding</h3>
        <p className="text-xs text-[var(--muted-foreground)]">
          Áp dụng cho cả web (sidebar, login, browser title) và Discord presence của bot.
        </p>
      </div>

      <div>
        <Label>Tên hệ thống (hiển thị trên web)</Label>
        <Input
          value={systemName}
          onChange={e => setSystemName(e.target.value)}
          maxLength={maxName + 20}
          className="mt-1"
          disabled={loading || saving}
          placeholder="VD: Capy Medic"
        />
        <div className="flex justify-between text-xs mt-1">
          <span className={cn(
            'text-[var(--muted-foreground)]',
            nameTooLong && 'text-[var(--destructive)]',
            nameEmpty && 'text-[var(--destructive)]',
          )}>
            {nameEmpty
              ? 'Không được rỗng'
              : nameTooLong
                ? `Vượt ${maxName} ký tự (hiện ${systemName.trim().length})`
                : 'Sidebar, login, browser title sẽ dùng tên này'}
          </span>
          <span className="text-[var(--muted-foreground)]">{systemName.trim().length} / {maxName}</span>
        </div>
      </div>

      <div>
        <Label>Discord presence — text "đang xem ..."</Label>
        <Input
          value={botActivity}
          onChange={e => setBotActivity(e.target.value)}
          maxLength={maxActivity + 20}
          className="mt-1"
          disabled={loading || saving}
          placeholder="VD: Capy Medic | /log upload"
        />
        <div className="flex justify-between text-xs mt-1">
          <span className={cn(
            'text-[var(--muted-foreground)]',
            activityTooLong && 'text-[var(--destructive)]',
            activityEmpty && 'text-[var(--destructive)]',
          )}>
            {activityEmpty
              ? 'Không được rỗng'
              : activityTooLong
                ? `Vượt ${maxActivity} ký tự`
                : 'Bot Discord sẽ hiển thị "Đang xem <text>" trong vòng 60 giây'}
          </span>
          <span className="text-[var(--muted-foreground)]">{botActivity.trim().length} / {maxActivity}</span>
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-[var(--destructive)]/10 text-[var(--destructive)] text-sm">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
          {error}
        </div>
      )}

      {savedAt && !error && !dirty && (
        <div className="flex items-center gap-2 text-xs text-[var(--success)]">
          <span>✓</span>
          Đã lưu lúc {savedAt.toLocaleTimeString('vi-VN')} — bot sẽ cập nhật presence trong 60s.
        </div>
      )}

      <Button onClick={save} disabled={!canSave || saving || loading} className="w-full">
        <Save className="h-4 w-4" />
        {saving ? 'Đang lưu...' : loading ? 'Đang tải...' : dirty ? 'Lưu thay đổi' : 'Đã đồng bộ'}
      </Button>
    </Card>
  );
}

// ─── Role Map Tab (Vai trò) — Discord role thật của guild ────────────────────

function RoleMapTab({ guildId, guildName }: { guildId: string | null; guildName: string }) {
  const [data, setData] = useState<{
    role_map: Record<'DUTY_ADMIN' | 'DUTY_MOD' | 'DUTY_MEMBER', { role_id: string; role_name: string | null } | null>;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!guildId) {
      // Reset khi switch sang guild khác (hoặc logout) để không hiển thị data cũ
      setData(null);
      return;
    }
    setLoading(true);
    setError(null);
    api.setupGetRoles(guildId)
      .then(setData)
      .catch(err => setError(formatError(err)))
      .finally(() => setLoading(false));
  }, [guildId]);

  if (loading) {
    return (
      <Card className="p-6 max-w-3xl">
        <p className="text-sm text-[var(--muted-foreground)]">Đang tải role map của <strong>{guildName}</strong>...</p>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="p-6 max-w-3xl">
        <div className="flex items-start gap-2 p-3 rounded-lg bg-[var(--destructive)]/10 text-[var(--destructive)] text-sm">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
          {error}
        </div>
      </Card>
    );
  }

  const rolesDescription: Record<'DUTY_ADMIN' | 'DUTY_MOD' | 'DUTY_MEMBER', string> = {
    DUTY_ADMIN: 'Toàn quyền — sửa lịch, cấu hình bot, xoá log',
    DUTY_MOD: 'Quản lý — duyệt đơn nghỉ, xem audit log',
    DUTY_MEMBER: 'Member thường — chấm công, xem stats cá nhân',
  };

  return (
    <Card className="p-6 max-w-3xl">
      <h3 className="font-semibold mb-2">Map System Role → Discord Role</h3>
      <p className="text-sm text-[var(--muted-foreground)] mb-4">
        Mỗi role hệ thống được map tới 1 Discord role thật trong <strong>{guildName || 'guild này'}</strong>.
        Bot kiểm tra role này khi check quyền.
      </p>

      <div className="space-y-2">
        {(['DUTY_ADMIN', 'DUTY_MOD', 'DUTY_MEMBER'] as const).map(sysRole => {
          const entry = data?.role_map[sysRole] ?? null;
          return (
            <div key={sysRole} className="flex items-center gap-3 py-3 border-b border-[var(--border)] last:border-0">
              <div className="flex-1">
                <p className="text-sm font-bold">{sysRole}</p>
                <p className="text-[10px] text-[var(--muted-foreground)]">{rolesDescription[sysRole]}</p>
              </div>
              <span className="text-[var(--muted-foreground)]">→</span>
              <div className="w-[260px] text-right">
                {entry ? (
                  <>
                    <p className="text-sm font-medium">{entry.role_name || '(không resolve được tên)'}</p>
                    <p className="font-mono text-[10px] text-[var(--muted-foreground)]">{entry.role_id}</p>
                  </>
                ) : (
                  <span className="text-xs text-[var(--muted-foreground)]">— Chưa map —</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <p className="text-xs text-[var(--muted-foreground)] mt-3 p-3 bg-[var(--info)]/5 rounded-lg border-l-2 border-[var(--info)]">
        💡 Để sửa, vào Discord chạy <code className="bg-[var(--muted)] px-1 rounded">/setup role admin @role</code> /
        <code className="bg-[var(--muted)] px-1 rounded">/setup role mod @role</code> /
        <code className="bg-[var(--muted)] px-1 rounded">/setup role member @role</code>.
        Slash command có audit log + kiểm tra bot permission tự động.
      </p>
    </Card>
  );
}

// ─── Notifications Tab ────────────────────────────────────────────────────────

const NOTIFY_OPTIONS: Array<{ key: string; label: string; desc: string; icon: string }> = [
  {
    key: 'remind_register_shift',
    icon: '📋',
    label: 'Nhắc đăng ký ca trực',
    desc: 'Khi nhân viên mới nhận role medic mà chưa đăng ký lịch — bot tự DM nhắc nhở định kỳ',
  },
  {
    key: 'remind_before_shift',
    icon: '🔔',
    label: 'Nhắc trước giờ trực',
    desc: 'Trước giờ ca theo các mốc đã config (mặc định 60p, 30p, 5p) — bot tag user trong channel',
  },
  {
    key: 'alert_late',
    icon: '⏰',
    label: 'Cảnh báo đi muộn',
    desc: 'Khi qua giờ bắt đầu ca mà nhân viên chưa chấm công — DM cá nhân + báo admin',
  },
  {
    key: 'alert_burnout',
    icon: '🚨',
    label: 'Cảnh báo burnout',
    desc: 'Khi nhân viên trực quá nhiều giờ trong tuần (vượt ngưỡng) — tag admin',
  },
  {
    key: 'daily_digest',
    icon: '📊',
    label: 'Daily digest 8h sáng',
    desc: 'Tổng kết hoạt động hôm qua: top giờ trực, ai đi muộn, đơn nghỉ mới...',
  },
];

function NotificationsTab({ guildId }: { guildId: string | null }) {
  const [settings, setSettings] = useState<Record<string, boolean>>({});
  const [original, setOriginal] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<Date | null>(null);

  useEffect(() => {
    if (!guildId) return;
    setLoading(true);
    api.notificationSettings(guildId)
      .then(r => {
        setSettings(r.notification_settings || {});
        setOriginal(r.notification_settings || {});
      })
      .catch(err => setError(formatError(err)))
      .finally(() => setLoading(false));
  }, [guildId]);

  const dirty = JSON.stringify(settings) !== JSON.stringify(original);

  const save = async () => {
    if (!guildId) return;
    const note = await promptNote({
      title: 'Cập nhật cấu hình thông báo',
      description: 'Nhập lý do thay đổi để ghi audit log. Tối thiểu 3 ký tự.',
      placeholder: 'VD: tắt nhắc burnout theo yêu cầu admin...',
      minLength: 3,
    });
    if (note === null) return;
    setSaving(true);
    setError(null);
    try {
      const r = await api.notificationSettingsUpdate(guildId, settings, note);
      setOriginal(r.notification_settings);
      setSavedAt(new Date());
    } catch (err) {
      setError(formatError(err));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <Card className="p-6 max-w-2xl"><p className="text-sm text-[var(--muted-foreground)]">Đang tải...</p></Card>;
  }

  return (
    <Card className="p-6 max-w-2xl space-y-3">
      <div className="mb-2">
        <h3 className="font-semibold">Bật/tắt thông báo</h3>
        <p className="text-sm text-[var(--muted-foreground)]">
          Bot sẽ chỉ gửi các loại thông báo được bật ở đây
        </p>
      </div>

      {NOTIFY_OPTIONS.map(opt => (
        <label
          key={opt.key}
          className="flex items-center justify-between gap-3 p-3 rounded-lg border border-[var(--border)] hover:bg-[var(--muted)]/40 cursor-pointer transition-colors"
        >
          <div className="flex items-start gap-3 flex-1 min-w-0">
            <span className="text-xl shrink-0">{opt.icon}</span>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium">{opt.label}</p>
              <p className="text-xs text-[var(--muted-foreground)] leading-relaxed">{opt.desc}</p>
            </div>
          </div>
          <input
            type="checkbox"
            checked={!!settings[opt.key]}
            onChange={e => setSettings({ ...settings, [opt.key]: e.target.checked })}
            className="w-5 h-5 accent-[var(--primary)] shrink-0"
          />
        </label>
      ))}

      {error && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-[var(--destructive)]/10 text-[var(--destructive)] text-sm">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
          {error}
        </div>
      )}

      <div className="pt-3 flex justify-between items-center border-t border-[var(--border)]">
        <p className="text-xs text-[var(--muted-foreground)]">
          {savedAt && `Đã lưu lúc ${savedAt.toLocaleTimeString('vi-VN')}`}
        </p>
        <Button onClick={save} disabled={!dirty || saving}>
          <Save className="h-4 w-4" />
          {saving ? 'Đang lưu...' : dirty ? 'Lưu thay đổi' : 'Đã đồng bộ'}
        </Button>
      </div>
    </Card>
  );
}
