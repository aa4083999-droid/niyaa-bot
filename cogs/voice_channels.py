import asyncio
import logging
import time

import discord
from discord.ext import commands, tasks

log = logging.getLogger(__name__)

# ==================== 配置區域 ====================
TRIGGER_CHANNEL_ID = 1510980890682200124  # 觸發創房的語音頻道 ID
REST_CHANNEL_ID = 1517983383052091523     # 休息區 / AFK 語音頻道 ID

# 3 秒輪詢與 10 秒門檻
MUTE_CHECK_INTERVAL = 3.0
MUTE_TIMEOUT = 10.0
TEMP_CHANNEL_PREFIX = "🔊 "
# ===================================================


class TempVoiceCog(commands.Cog):
    """建立臨時語音頻道，並將長時間靜音的成員移至休息區。"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # 使用 monotonic 時鐘記錄開始靜音時間，避免系統時間調整影響計時。
        self.mute_started_at: dict[tuple[int, int], float] = {}

        # 記錄本次啟動期間由本 Cog 建立的頻道。
        self.temp_channel_ids: set[int] = set()

        # 避免同時建立多個 Discord 頻道。
        self._create_lock = asyncio.Lock()

        # 避免多個離開事件同時刪除同一個頻道。
        self._delete_lock = asyncio.Lock()

        # 防止同一位使用者因 Gateway 重複事件重複建立房間。
        self._creating_for: set[tuple[int, int]] = set()

        self.check_afk_loop.start()
        log.info("TempVoiceCog 已啟動（驗收模式：3秒輪詢 / 10秒靜音門檻）")

    def cog_unload(self):
        self.check_afk_loop.cancel()

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
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        entered_trigger = (
            after.channel is not None
            and after.channel.id == TRIGGER_CHANNEL_ID
            and (
                before.channel is None
                or before.channel.id != TRIGGER_CHANNEL_ID
            )
        )

        if entered_trigger:
            await self._create_temp_channel(member, after.channel)

        if self._is_temp_channel(before.channel):
            await self._delete_if_empty(before.channel)

        if (
            not self._is_temp_channel(after.channel)
            or not (after.self_mute or after.mute)
        ):
            self.mute_started_at.pop(
                self._mute_key(member),
                None,
            )

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
                log.exception("建立或移動臨時語音頻道時權限不足")

            except discord.HTTPException:
                log.exception("建立或移動臨時語音頻道時發生 Discord API 錯誤")

            finally:
                self._creating_for.discard(key)

                if new_channel is not None and (
                    member.voice is None
                    or member.voice.channel != new_channel
                ):
                    self.temp_channel_ids.discard(new_channel.id)

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
            await asyncio.sleep(0.25)

            if (
                channel.id not in self.temp_channel_ids
                or len(channel.members) > 0
            ):
                return

            self.temp_channel_ids.discard(channel.id)

            try:
                await channel.delete(reason="臨時語音頻道已無人使用，自動刪除")
                log.info("已清理空臨時語音頻道：%s (%s)", channel.name, channel.id)
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
            ):
                log.exception("刪除空臨時語音頻道失敗：%s", channel.id)

    @tasks.loop(seconds=MUTE_CHECK_INTERVAL)
    async def check_afk_loop(self):
        now = time.monotonic()

        for guild in self.bot.guilds:
            rest_channel = guild.get_channel(REST_CHANNEL_ID)
            if rest_channel is None or not isinstance(rest_channel, discord.VoiceChannel):
                continue

            for channel in guild.voice_channels:
                if not self._is_temp_channel(channel):
                    continue

                for member in channel.members:
                    if member.bot:
                        continue

                    is_muted = member.voice.self_mute or member.voice.mute

                    key = self._mute_key(member)

                    if is_muted:
                        start_time = self.mute_started_at.setdefault(key, now)
                        if now - start_time >= MUTE_TIMEOUT:
                            try:
                                await member.move_to(
                                    rest_channel,
                                    reason=f"連續靜音滿 {MUTE_TIMEOUT} 秒，自動移至休息區",
                                )
                                log.info(
                                    "已將成員 %s 移至休息區，因靜音已滿 %.1f 秒",
                                    member.display_name,
                                    now - start_time,
                                )
                            except (discord.Forbidden, discord.HTTPException):
                                log.exception(
                                    "將成員 %s 移動至休息區失敗",
                                    member.display_name,
                                )
                            finally:
                                self.mute_started_at.pop(key, None)
                    else:
                        self.mute_started_at.pop(key, None)

    @check_afk_loop.before_loop
    async def before_check_afk_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(TempVoiceCog(bot))
