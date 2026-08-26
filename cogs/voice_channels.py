import asyncio
import json
import logging
import os
import time

import discord
from discord.ext import commands, tasks

log = logging.getLogger(__name__)

TRIGGER_CHANNEL_ID = 1510980890682200124
REST_CHANNEL_ID = 1517983383052091523

# 設定：3 秒輪詢，30 分鐘靜音門檻
MUTE_CHECK_INTERVAL = 3.0
MUTE_TIMEOUT = 30 * 60.0
# 移動失敗時的重試冷卻時間（60 秒，避免每 3 秒連續轟炸 API）
MOVE_RETRY_COOLDOWN = 60.0

TEMP_CHANNEL_PREFIX = "🔊 "
DATA_FILE = "data/temp_voice_channels.json"


class TempVoiceCog(commands.Cog):
    """建立臨時語音頻道，並將長時間靜音的成員移至休息區（具備持久化與完善防護）。"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # 使用 monotonic 時鐘記錄開始靜音時間，避免系統時間調整影響計時。
        self.mute_started_at: dict[tuple[int, int], float] = {}

        # 記錄移動失敗的冷卻時間點 { (guild_id, member_id): monotonic_timestamp }
        self.move_failed_at: dict[tuple[int, int], float] = {}

        # 記錄本 Cog 管理的臨時頻道 ID 集合
        self.temp_channel_ids: set[int] = set()

        # 避免同時建立多個 Discord 頻道
        self._create_lock = asyncio.Lock()

        # 避免多個離開事件同時刪除同一個頻道
        self._delete_lock = asyncio.Lock()

        # 防止同一位使用者因 Gateway 重複事件重複建立房間
        self._creating_for: set[tuple[int, int]] = set()

        # 載入持久化資料
        self._load_persisted_channels()

        self.check_afk_loop.start()
        log.info(
            "TempVoiceCog 已啟動（輪詢間隔：%.1f秒 / 靜音門檻：%.0f分鐘）",
            MUTE_CHECK_INTERVAL,
            MUTE_TIMEOUT / 60,
        )

    def cog_unload(self):
        self.check_afk_loop.cancel()

    # --- 持久化輔助方法 ---

    def _ensure_data_dir(self):
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)

    def _load_persisted_channels(self):
        if not os.path.exists(DATA_FILE):
            return
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    self.temp_channel_ids = set(int(cid) for cid in data)
            log.info("已從 %s 載入 %d 個暫存頻道紀錄。", DATA_FILE, len(self.temp_channel_ids))
        except Exception:
            log.exception("讀取暫存頻道持久化檔案失敗")

    def _save_persisted_channels(self):
        try:
            self._ensure_data_dir()
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(list(self.temp_channel_ids), f)
        except Exception:
            log.exception("儲存暫存頻道持久化檔案失敗")

    def _is_temp_channel(
        self,
        channel: discord.abc.GuildChannel | None,
    ) -> bool:
        if channel is None or channel.id == TRIGGER_CHANNEL_ID:
            return False
        return channel.id in self.temp_channel_ids

    @staticmethod
    def _mute_key(member: discord.Member) -> tuple[int, int]:
        return member.guild.id, member.id

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        """當頻道被刪除時，同步從追蹤集合與檔案中移除"""
        if channel.id in self.temp_channel_ids:
            self.temp_channel_ids.discard(channel.id)
            self._save_persisted_channels()

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.bot:
            return

        key = self._mute_key(member)

        # 1. 偵測進入觸發頻道
        entered_trigger = (
            after.channel is not None
            and after.channel.id == TRIGGER_CHANNEL_ID
            and (
                before.channel is None
                or before.channel.id != TRIGGER_CHANNEL_ID
            )
        )

        if entered_trigger:
            asyncio.create_task(
                self._create_temp_channel(member, after.channel)
            )

        # 2. 偵測離開臨時頻道（若空了就刪除）
        if self._is_temp_channel(before.channel) and (
            after.channel is None or after.channel.id != before.channel.id
        ):
            asyncio.create_task(self._delete_if_empty(before.channel))

        # 3. 檢查是否解除靜音或離開臨時頻道，若是則清除計時紀錄與失敗冷卻
        is_muted = after.self_mute or after.mute
        if not self._is_temp_channel(after.channel) or not is_muted:
            self.mute_started_at.pop(key, None)
            self.move_failed_at.pop(key, None)

    async def _create_temp_channel(
        self,
        member: discord.Member,
        trigger_channel: discord.VoiceChannel,
    ):
        key = self._mute_key(member)

        if key in self._creating_for:
            return

        self._creating_for.add(key)

        async with self._create_lock:
            # 再次確認成員是否還在觸發頻道內
            if (
                member.voice is None
                or member.voice.channel != trigger_channel
            ):
                self._creating_for.discard(key)
                return

            channel_name = f"{TEMP_CHANNEL_PREFIX}{member.display_name} 的房間"
            new_channel: discord.VoiceChannel | None = None

            try:
                new_channel = await member.guild.create_voice_channel(
                    name=channel_name,
                    category=trigger_channel.category,
                    reason=f"{member.display_name} 建立的臨時語音頻道",
                )

                self.temp_channel_ids.add(new_channel.id)
                self._save_persisted_channels()

                await member.move_to(
                    new_channel,
                    reason="移動至新建立的臨時語音頻道",
                )

                log.info(
                    "已建立臨時語音頻道：%s (%s)",
                    new_channel.name,
                    new_channel.id,
                )

            except discord.Forbidden:
                log.error("建立或移動臨時語音頻道時權限不足 (Forbidden)")
            except discord.HTTPException:
                log.exception("建立或移動臨時語音頻道時發生 Discord API 錯誤")
            finally:
                self._creating_for.discard(key)

                # 若建立後成員未能成功移動，作為防護清理孤兒頻道
                if new_channel is not None and (
                    member.voice is None
                    or member.voice.channel != new_channel
                ):
                    self.temp_channel_ids.discard(new_channel.id)
                    self._save_persisted_channels()
                    try:
                        await new_channel.delete(
                            reason="成員未能移動至臨時語音頻道，清理孤兒頻道",
                        )
                    except (
                        discord.NotFound,
                        discord.Forbidden,
                        discord.HTTPException,
                    ):
                        log.exception(
                            "清理孤兒臨時頻道失敗：%s", new_channel.id
                        )

    async def _delete_if_empty(
        self,
        channel: discord.VoiceChannel,
    ):
        async with self._delete_lock:
            # 短暫延遲防抖，確保成員完全離開狀態穩定
            await asyncio.sleep(0.5)

            # 重新取得最新頻道物件或檢查成員
            if (
                channel.id not in self.temp_channel_ids
                or len(channel.members) > 0
            ):
                return

            try:
                await channel.delete(
                    reason="臨時語音頻道已無人使用，自動清理",
                )
                log.info(
                    "已刪除空的臨時語音頻道：%s (%s)",
                    channel.name,
                    channel.id,
                )
                self.temp_channel_ids.discard(channel.id)
                self._save_persisted_channels()
            except discord.NotFound:
                self.temp_channel_ids.discard(channel.id)
                self._save_persisted_channels()
            except discord.Forbidden:
                log.error("刪除臨時語音頻道失敗：權限不足 (%s)", channel.id)
            except discord.HTTPException:
                log.exception("刪除臨時語音頻道失敗：%s", channel.id)
                # 保留追蹤 ID 稍後再試

    @tasks.loop(seconds=MUTE_CHECK_INTERVAL)
    async def check_afk_loop(self):
        now = time.monotonic()
        active_keys: set[tuple[int, int]] = set()

        for guild in self.bot.guilds:
            rest_channel = guild.get_channel(REST_CHANNEL_ID)

            for channel in guild.voice_channels:
                # 補充檢查：若空了順便清理（防堵漏掉的離開事件）
                if self._is_temp_channel(channel) and len(channel.members) == 0:
                    asyncio.create_task(self._delete_if_empty(channel))
                    continue

                if not self._is_temp_channel(channel):
                    continue

                for member in channel.members:
                    try:
                        voice_state = member.voice
                        key = self._mute_key(member)

                        if (
                            voice_state is None
                            or voice_state.channel != channel
                        ):
                            self.mute_started_at.pop(key, None)
                            self.move_failed_at.pop(key, None)
                            continue

                        is_muted = voice_state.self_mute or voice_state.mute

                        if not is_muted:
                            self.mute_started_at.pop(key, None)
                            self.move_failed_at.pop(key, None)
                            continue

                        active_keys.add(key)
                        self.mute_started_at.setdefault(key, now)
                        started_at = self.mute_started_at[key]

                        if now - started_at < MUTE_TIMEOUT:
                            continue

                        # 檢查是否處於移動失敗的冷卻期內
                        last_fail = self.move_failed_at.get(key, 0.0)
                        if now - last_fail < MOVE_RETRY_COOLDOWN:
                            continue

                        if not isinstance(rest_channel, discord.VoiceChannel):
                            continue

                        # 再次確認狀態後執行移動
                        if (
                            member.voice
                            and member.voice.channel == channel
                            and (member.voice.self_mute or member.voice.mute)
                        ):
                            try:
                                await member.move_to(
                                    rest_channel,
                                    reason="在臨時語音頻道靜音過久，自動移至休息區",
                                )
                                log.info("已將長時間靜音成員 %s 移至休息區", member)
                                # 移動成功後才清除計時器與失敗紀錄
                                self.mute_started_at.pop(key, None)
                                self.move_failed_at.pop(key, None)
                            except (discord.Forbidden, discord.HTTPException):
                                # 記錄失敗時間，進入冷卻期避免每 3 秒洗版
                                self.move_failed_at[key] = now
                                raise

                    except discord.Forbidden:
                        log.error("移動 %s 至休息區時權限不足（已進入 60 秒冷卻）", member)
                    except discord.HTTPException:
                        log.exception(
                            "移動 %s 至休息區時發生 Discord API 錯誤（已進入 60 秒冷卻）", member
                        )
                    except Exception:
                        log.exception("檢核成員 AFK 狀態時發生未預期錯誤")

        # 清理已不在暫存頻道內或不再靜音的快取資料
        stale_keys = set(self.mute_started_at) - active_keys
        for key in stale_keys:
            self.mute_started_at.pop(key, None)
            self.move_failed_at.pop(key, None)

    @check_afk_loop.error
    async def check_afk_loop_error(self, error: Exception):
        log.exception("AFK 檢查迴圈發生嚴重例外而停止：%s", error)

    @check_afk_loop.before_loop
    async def before_check_afk_loop(self):
        await self.bot.wait_until_ready()

        # 啟動時清理已不存在 Discord 伺服器中的暫存頻道 ID (防止機器人重啟後殘留)
        valid_ids = set()
        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                if channel.id in self.temp_channel_ids:
                    valid_ids.add(channel.id)
                    # 同時順便檢查重啟時如果頻道剛好是空的，直接清理掉
                    if len(channel.members) == 0:
                        asyncio.create_task(self._delete_if_empty(channel))

        if valid_ids != self.temp_channel_ids:
            self.temp_channel_ids = valid_ids
            self._save_persisted_channels()
            log.info("已清理重啟後失效的暫存頻道紀錄。")

        # 驗證休息區頻道
        rest_channel = self.bot.get_channel(REST_CHANNEL_ID)
        if not isinstance(rest_channel, discord.VoiceChannel):
            log.warning(
                "【注意】指定的 REST_CHANNEL_ID (%s) 無效或不是語音頻道，長時間靜音移動功能將無法運作！",
                REST_CHANNEL_ID,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(TempVoiceCog(bot))
