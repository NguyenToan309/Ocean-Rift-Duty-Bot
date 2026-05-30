"""
test_save_duty_log.py — Unit test cho _save_duty_log() trong bot/cogs/log_duty.py

Kiểm tra 4 tầng bảo vệ:
  Tầng 0 — Ca trực không được ở tương lai
  Tầng 1 — source_message_id unique (chặn scan trùng)
  Tầng 2 — (guild_id, user_id, started_at, ended_at) exact duplicate
  Tầng 3 — Overlap check (ca trực không được chồng lấp)

Chạy: pytest tests/test_save_duty_log.py -v
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from bot.cogs.log_duty import _save_duty_log
from conftest import (
    make_session, make_duty_log_mock,
    GUILD_ID, USER_ID, MOD_ID,
    T_START, T_END,
)

# ─── Helper: params mặc định ─────────────────────────────────────────────────

BASE_PARAMS = dict(
    guild_id=GUILD_ID,
    user_id=USER_ID,
    username="Nguyễn Văn A",
    started_at=T_START,          # 2026-05-01 01:00 UTC (ngày hôm qua, an toàn)
    ended_at=T_END,              # 2026-05-01 03:00 UTC
    duration_minutes=120,
    raw_text="LOG DUTY ...",
    source="message",
    source_message_id=None,
    submitted_by=MOD_ID,
)

MSG_ID = 987654321098765432


# ─── Tầng 0: Kiểm tra tương lai ──────────────────────────────────────────────

class TestLayer0Future:
    """Ca trực ở tương lai phải bị chặn ngay, không cần query DB"""

    async def test_future_start_raises(self, future_start, future_end):
        """started_at > utcnow() + 30 phút → ValueError"""
        session = make_session()  # sẽ không bị gọi execute nào
        with pytest.raises(ValueError, match="chưa bắt đầu"):
            await _save_duty_log(
                **{**BASE_PARAMS, "started_at": future_start, "ended_at": future_end},
                session=session,
            )

    async def test_future_end_raises(self, past_start, future_end):
        """ended_at > utcnow() + 5 phút → ValueError dù started_at hợp lệ"""
        session = make_session()
        with pytest.raises(ValueError, match="chưa kết thúc"):
            await _save_duty_log(
                **{**BASE_PARAMS, "started_at": past_start, "ended_at": future_end},
                session=session,
            )

    async def test_past_start_passes_layer0(self):
        """started_at trong quá khứ → qua được tầng 0, tiếp tục kiểm tra các tầng sau"""
        # make_session(None, None, None, None): tầng 2 = None (no dup), tầng 3 = None (no overlap)
        session = make_session(None, None, None, None)
        log = await _save_duty_log(**BASE_PARAMS, session=session)
        assert log is not None

    @patch("bot.cogs.log_duty.utcnow")
    async def test_start_within_30min_buffer_error_is_not_started(self, mock_utcnow):
        """
        started_at trong buffer 30 phút → KHÔNG lỗi 'chưa bắt đầu' mà lỗi 'chưa kết thúc'
        Verify rằng started_at check dùng buffer đúng cách: error nhảy qua lỗi started → đến lỗi ended.
        """
        # Mock "now" = T_START - 20 phút → T_START là "now + 20 phút" (trong buffer 30 phút)
        # T_END = T_START + 2h = "now + 2h20m" (vượt buffer 5 phút → lỗi kết thúc)
        mock_utcnow.return_value = T_START - timedelta(minutes=20)
        session = make_session()
        with pytest.raises(ValueError) as exc_info:
            await _save_duty_log(**BASE_PARAMS, session=session)
        # Phải là lỗi "chưa kết thúc", KHÔNG phải "chưa bắt đầu"
        assert "kết thúc" in str(exc_info.value)
        assert "bắt đầu" not in str(exc_info.value)

    async def test_ended_at_5min_buffer(self):
        """ended_at = utcnow() + 3 phút → trong buffer 5 phút → được phép"""
        from bot.utils.time_utils import utcnow
        past_s = utcnow() - timedelta(hours=2)
        near_end = utcnow() + timedelta(minutes=3)
        actual_mins = int((near_end - past_s).total_seconds() / 60)

        session = make_session(None, None, None, None)
        log = await _save_duty_log(
            **{**BASE_PARAMS,
               "started_at": past_s,
               "ended_at": near_end,
               "duration_minutes": actual_mins},
            session=session,
        )
        assert log is not None


# ─── Tầng 1: source_message_id duplicate ─────────────────────────────────────

class TestLayer1MessageId:
    """Cùng một message Discord không được lưu 2 lần"""

    async def test_duplicate_message_id_raises(self):
        """Execute #1 (source_message_id check) trả về existing → ValueError"""
        existing = make_duty_log_mock()
        # source_message_id != None → execute #1 là layer 1 check
        session = make_session(None, None, existing)  # layer1 = existing → raise
        with pytest.raises(ValueError, match="duplicate|đã được lưu"):
            await _save_duty_log(
                **{**BASE_PARAMS, "source_message_id": MSG_ID},
                session=session,
            )

    async def test_no_message_id_skips_layer1(self):
        """source_message_id=None → bỏ qua tầng 1, thực hiện tầng 2 và 3"""
        # source_message_id=None, không có exact dup, không có overlap
        session = make_session(None, None, None, None)   # tầng 2 = None, tầng 3 = None
        log = await _save_duty_log(**BASE_PARAMS, session=session)
        assert log is not None

    async def test_new_message_id_passes_layer1(self):
        """source_message_id mới (không có trong DB) → qua tầng 1"""
        # execute #1 = None (không tìm thấy message_id này)
        # execute #2 = None (không dup), execute #3 = None (không overlap)
        session = make_session(None, None, None, None, None)
        log = await _save_duty_log(
            **{**BASE_PARAMS, "source_message_id": MSG_ID},
            session=session,
        )
        assert log is not None


# ─── Tầng 2: Exact duplicate ─────────────────────────────────────────────────

class TestLayer2ExactDuplicate:
    """Cùng (guild, user, start, end) không được lưu 2 lần"""

    async def test_exact_duplicate_raises(self):
        """Execute tầng 2 trả về existing log → ValueError 'đã được lưu'"""
        existing = make_duty_log_mock()
        # source_message_id=None → execute #1 = tầng 2, trả về existing
        session = make_session(None, None, existing)
        with pytest.raises(ValueError, match="đã được lưu"):
            await _save_duty_log(**BASE_PARAMS, session=session)

    async def test_different_user_same_time_allowed(self):
        """Cùng thời gian nhưng user khác → KHÔNG phải exact dup → được phép"""
        # Layer 2 trả None (vì query có guild_id+user_id filter — user khác thì kết quả khác)
        # Trong test: session mock trả None = "không tìm thấy"
        session = make_session(None, None, None, None)
        log = await _save_duty_log(
            **{**BASE_PARAMS, "user_id": USER_ID + 1},   # user khác
            session=session,
        )
        assert log is not None

    async def test_different_guild_same_data_allowed(self):
        """Cùng user+time nhưng guild khác → không phải dup của guild này"""
        session = make_session(None, None, None, None)
        log = await _save_duty_log(
            **{**BASE_PARAMS, "guild_id": GUILD_ID + 999},
            session=session,
        )
        assert log is not None

    async def test_different_time_not_dup(self):
        """Cùng user nhưng thời gian khác → không phải exact dup"""
        other_start = T_START - timedelta(days=1)
        other_end = T_END - timedelta(days=1)
        session = make_session(None, None, None, None)
        log = await _save_duty_log(
            **{**BASE_PARAMS, "started_at": other_start, "ended_at": other_end},
            session=session,
        )
        assert log is not None


# ─── Tầng 3: Overlap check ───────────────────────────────────────────────────

class TestLayer3Overlap:
    """Ca trực mới không được chồng lấp thời gian với ca đã có"""

    async def test_full_overlap_raises(self):
        """Ca mới nằm hoàn toàn bên trong ca cũ → ValueError 'chồng lấp'"""
        # Ca cũ 08:00-10:00, ca mới 08:30-09:30 (nằm trong)
        conflict = make_duty_log_mock(started_at=T_START, ended_at=T_END)
        session = make_session(None, None, None, conflict)  # tầng2=None, tầng3=conflict
        with pytest.raises(ValueError, match="chồng lấp"):
            await _save_duty_log(**BASE_PARAMS, session=session)

    async def test_partial_overlap_start_raises(self):
        """Ca mới bắt đầu giữa ca cũ, kết thúc sau ca cũ → chồng lấp"""
        conflict = make_duty_log_mock(started_at=T_START, ended_at=T_END)
        mid = T_START + timedelta(hours=1)      # 02:00 UTC = giữa ca cũ
        after = T_END + timedelta(hours=1)      # 04:00 UTC = sau ca cũ
        session = make_session(None, None, None, conflict)
        with pytest.raises(ValueError, match="chồng lấp"):
            await _save_duty_log(
                **{**BASE_PARAMS, "started_at": mid, "ended_at": after,
                   "duration_minutes": 120},
                session=session,
            )

    async def test_partial_overlap_end_raises(self):
        """Ca mới kết thúc giữa ca cũ → chồng lấp"""
        conflict = make_duty_log_mock(started_at=T_START, ended_at=T_END)
        before = T_START - timedelta(hours=1)   # bắt đầu trước ca cũ
        mid = T_START + timedelta(hours=1)      # kết thúc giữa ca cũ
        session = make_session(None, None, None, conflict)
        with pytest.raises(ValueError, match="chồng lấp"):
            await _save_duty_log(
                **{**BASE_PARAMS, "started_at": before, "ended_at": mid,
                   "duration_minutes": 120},
                session=session,
            )

    async def test_adjacent_shift_after_allowed(self):
        """Ca mới bắt đầu ĐÚNG lúc ca cũ kết thúc → hợp lệ (ca liên tiếp)"""
        # Thuật toán: A.start < B.end AND A.end > B.start
        # Ca mới start=T_END, end=T_END+2h → T_END < T_END? → False → không overlap
        session = make_session(None, None, None, None)  # tầng3 trả None = không overlap
        new_start = T_END                   # = 03:00 UTC
        new_end = T_END + timedelta(hours=2)
        log = await _save_duty_log(
            **{**BASE_PARAMS, "started_at": new_start, "ended_at": new_end,
               "duration_minutes": 120},
            session=session,
        )
        assert log is not None

    async def test_adjacent_shift_before_allowed(self):
        """Ca mới kết thúc ĐÚNG lúc ca cũ bắt đầu → hợp lệ"""
        session = make_session(None, None, None, None)
        new_end = T_START                   # = 01:00 UTC
        new_start = T_START - timedelta(hours=2)
        log = await _save_duty_log(
            **{**BASE_PARAMS, "started_at": new_start, "ended_at": new_end,
               "duration_minutes": 120},
            session=session,
        )
        assert log is not None

    async def test_past_non_overlapping_allowed(self):
        """Ca khác ngày hoàn toàn → không overlap"""
        session = make_session(None, None, None, None)
        yesterday_start = T_START - timedelta(days=1)
        yesterday_end = T_END - timedelta(days=1)
        log = await _save_duty_log(
            **{**BASE_PARAMS, "started_at": yesterday_start, "ended_at": yesterday_end},
            session=session,
        )
        assert log is not None

    async def test_overlap_error_message_contains_times(self):
        """Error message phải hiển thị thời gian ca cũ để user biết lý do"""
        conflict = make_duty_log_mock(
            started_at=T_START, ended_at=T_END, duration_minutes=120
        )
        session = make_session(None, None, None, conflict)
        with pytest.raises(ValueError) as exc_info:
            await _save_duty_log(**BASE_PARAMS, session=session)
        msg = str(exc_info.value)
        assert "chồng lấp" in msg
        assert "120 phút" in msg


# ─── Happy path ───────────────────────────────────────────────────────────────

class TestSaveSuccess:
    """Kiểm tra ca trực hợp lệ được lưu đúng cách"""

    async def test_returns_duty_log_object(self):
        """Hàm phải trả về DutyLog object khi thành công"""
        from models.duty_log import DutyLog
        session = make_session(None, None, None, None)
        log = await _save_duty_log(**BASE_PARAMS, session=session)
        assert isinstance(log, DutyLog)

    async def test_session_add_called(self):
        """session.add() phải được gọi với DutyLog (và DutyIdentityBinding nếu first-time)"""
        session = make_session(None, None, None, None)
        log = await _save_duty_log(**BASE_PARAMS, session=session)
        # Lần đầu lưu → có 2 add: binding mới + duty_log
        assert session.add.call_count == 2
        # log object phải là một trong các add calls
        added_objs = [c.args[0] for c in session.add.call_args_list]
        assert log in added_objs

    async def test_saved_attributes_correct(self):
        """Các trường trong DutyLog phải khớp với input"""
        session = make_session(None, None, None, None)
        log = await _save_duty_log(**BASE_PARAMS, session=session)
        assert log.guild_id == GUILD_ID
        assert log.user_id == USER_ID
        assert log.username == "Nguyễn Văn A"
        assert log.started_at == T_START
        assert log.ended_at == T_END
        assert log.duration_minutes == 120
        assert log.source == "message"

    async def test_with_message_id_saved(self):
        """source_message_id được lưu vào log"""
        session = make_session(None, None, None, None, None)
        log = await _save_duty_log(
            **{**BASE_PARAMS, "source_message_id": MSG_ID},
            session=session,
        )
        assert log.source_message_id == MSG_ID

    async def test_session_not_committed(self):
        """_save_duty_log không tự commit — caller chịu trách nhiệm commit"""
        session = make_session(None, None, None, None)
        await _save_duty_log(**BASE_PARAMS, session=session)
        session.commit.assert_not_called()


# ─── DutyIdentityBinding scenarios ────────────────────────────────────────────

class TestBindingLogic:
    """5 scenario binding (Tầng -1) — replace cơ chế username lock cũ"""

    async def test_scenario_1_first_time_creates_binding(self):
        """Scenario 1: user chưa có binding + tên chưa thuộc ai → tạo binding mới"""
        # 2 execute đầu: own_binding=None, name_owner=None → create new
        session = make_session(None, None, None, None)
        log = await _save_duty_log(**BASE_PARAMS, session=session)
        assert log is not None
        # session.add gọi 2 lần: binding mới + duty_log
        assert session.add.call_count == 2

    async def test_scenario_2_matching_name_passes(self):
        """Scenario 2: user đã có binding + tên log khớp current → pass"""
        from models.duty_identity_binding import DutyIdentityBinding
        existing = DutyIdentityBinding(
            guild_id=GUILD_ID,
            discord_user_id=USER_ID,
            original_ingame_name="Nguyễn Văn A",
            current_ingame_name="Nguyễn Văn A",
            first_seen_at=T_START, last_seen_at=T_START,
            log_count=5, rebind_count=0, rebind_history=[],
        )
        # execute #1 = own_binding (existing), execute #2 = name_owner (skipped vì own match)
        # Actually code reads name_owner regardless. Trả existing cho both.
        session = make_session(existing, existing, None, None, None)
        log = await _save_duty_log(**BASE_PARAMS, session=session)
        assert log is not None
        # Binding hiện có nên session.add chỉ thêm DutyLog (KHÔNG add binding mới)
        assert session.add.call_count == 1
        # log_count tăng từ 5 → 6
        assert existing.log_count == 6

    async def test_scenario_3_mismatched_name_rejects(self):
        """Scenario 3: user đã có binding nhưng tên log KHÁC current → reject"""
        from models.duty_identity_binding import DutyIdentityBinding
        existing = DutyIdentityBinding(
            guild_id=GUILD_ID,
            discord_user_id=USER_ID,
            original_ingame_name="Báo Lê (CP890743)",
            current_ingame_name="Báo Lê (CP890743)",
            first_seen_at=T_START, last_seen_at=T_START,
            log_count=3, rebind_count=0, rebind_history=[],
        )
        session = make_session(existing, None)  # own_binding=existing, name_owner=None
        with pytest.raises(ValueError, match="không khớp với tên"):
            await _save_duty_log(
                **{**BASE_PARAMS, "username": "Khoa Cool (CP999999)"},
                session=session,
            )

    async def test_scenario_4_name_taken_by_other_user_rejects(self):
        """Scenario 4: user chưa có binding NHƯNG tên đã thuộc user khác → reject impersonation"""
        from models.duty_identity_binding import DutyIdentityBinding
        other_user_binding = DutyIdentityBinding(
            guild_id=GUILD_ID,
            discord_user_id=USER_ID + 999,   # user khác
            original_ingame_name="Nguyễn Văn A",
            current_ingame_name="Nguyễn Văn A",
            first_seen_at=T_START, last_seen_at=T_START,
            log_count=1, rebind_count=0, rebind_history=[],
        )
        # own_binding=None (chưa có), name_owner=other_user_binding (đã chiếm)
        session = make_session(None, other_user_binding)
        with pytest.raises(ValueError, match="thuộc về tài khoản Discord khác"):
            await _save_duty_log(**BASE_PARAMS, session=session)

    async def test_scenario_case_sensitive_match(self):
        """Tên 'Báo Lê' và 'BÁO LÊ' coi là KHÁC nhau (phân biệt hoa thường)"""
        from models.duty_identity_binding import DutyIdentityBinding
        existing = DutyIdentityBinding(
            guild_id=GUILD_ID,
            discord_user_id=USER_ID,
            original_ingame_name="Báo Lê",
            current_ingame_name="Báo Lê",   # lowercase b, uppercase B
            first_seen_at=T_START, last_seen_at=T_START,
            log_count=1, rebind_count=0, rebind_history=[],
        )
        session = make_session(existing, None)
        with pytest.raises(ValueError, match="không khớp"):
            await _save_duty_log(
                **{**BASE_PARAMS, "username": "BÁO LÊ"},   # ALL CAPS — khác
                session=session,
            )
