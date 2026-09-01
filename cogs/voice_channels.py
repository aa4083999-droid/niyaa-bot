import asyncio
import logging
import time

import discord
from discord.ext import commands, tasks


log = logging.getLogger(__name__)


TRIGGER_CHANNEL_ID = 1510980890682200124
REST_CHANNEL_ID = 1517983383052091523

MUTE_CHECK_INTERVAL = 3.0  # 每 3 秒檢查一次
MUTE_TIMEOUT = 30 * 60.0  # 正式門檻：靜音累積 30 分鐘
MOVE_RETRY_INTERVAL = 30.0  # 移動失敗時，至少隔 30 秒再重試
TEMP_CHANNEL_PREFIX = "🔊 "


class TempVoiceCog(commands.Cog):
    """建立臨時語音頻道，並將長時間靜音的成員移至休息區。"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # 使用 monotonic 時鐘記錄開始靜音時間，
        # 避免系統時間調整影響計時。
        self.mute_started_at: dict[tuple[int, int], float] = {}

        # 只記錄本次啟動期間由本 Cog 建立的頻道。
        self.temp_channel_ids: set[int] = set()

        # 避免同一位使用者快速切換頻道時建立多個臨時房。
        self._create_lock = asyncio.Lock()

        # 避免多個離開事件同時刪除同一個頻道。
        self._delete_lock = asyncio.Lock()

        # 防止同一位使用者因 Gateway 重複事件重複建立房間。
        self._creating_for: set[tuple[int, int]] = set()

        # 記錄移動失敗後的下次重試時間。
        self._move_retry_at: dict[tuple[int, int], float] = {}

        log.info("TempVoiceCog 已啟動（30 分鐘靜音門檻）")

    async def cog_load(self):
        # 等 Cog 完成載入後才啟動 task，避免在 setup、
        # 測試或熱重載階段因沒有 running event loop 而啟動失敗。
        self.check_afk_loop.start()

    def cog_unload(self):
        self.check_afk_loop.cancel()

    def _is_temp_channel(
        self,
        channel: discord.abc.GuildChannel | None,
    ) -> bool:
        if channel is None or channel.id == TRIGGER_CHANNEL_ID:
            return False

        # 不使用名稱前綴作為刪除依據。
        # 名稱可能被管理員或其他機器人仿造，
        # 不能讓名稱成為破壞性操作的 ownership 證明。
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
        # 只有真正進入觸發頻道時才建立房間。
        # 這也能避免成員在觸發頻道內靜音或取消靜音時重複開房。
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

        # 成員離開臨時頻道後，若已經沒有成員就刪除。
        if self._is_temp_channel(before.channel):
            await self._delete_if_empty(before.channel)

        key = self._mute_key(member)

        # 在事件發生的當下就開始計時，
        # 不必等下一輪背景輪詢。
        # 也涵蓋使用者進入臨時房時本來就已經靜音的情況。
        if (
            self._is_temp_channel(after.channel)
            and (after.self_mute or after.mute)
        ):
            if key not in self.mute_started_at:
                self.mute_started_at[key] = time.monotonic()

                # 重新開始一次靜音計時時，
                # 清除之前可能留下的重試等待時間。
                self._move_retry_at.pop(key, None)

                log.info("開始計算 %s 的靜音時間", member)
        else:
            # 離開臨時房、進入其他頻道或取消靜音時，
            # 立即清除對應的靜音計時與重試狀態。
            self.mute_started_at.pop(key, None)
            self._move_retry_at.pop(key, None)

    async def _create_temp_channel(
        self,
        member: discord.Member,
        trigger_channel: discord.VoiceChannel,
    ):
        key = self._mute_key(member)

        if key in self._creating_for:
            return

        self._creating_for.add(key)

        try:
            async with self._create_lock:
                # 事件排隊等待 lock 期間，
                # 使用者可能已經離開觸發頻道。
                if (
                    member.voice is None
                    or member.voice.channel != trigger_channel
                ):
                    return

                channel_name = (
                    f"{TEMP_CHANNEL_PREFIX}"
                    f"{member.display_name} 的房間"
                )

                new_channel: discord.VoiceChannel | None = None

                try:
                    new_channel = (
                        await member.guild.create_voice_channel(
                            name=channel_name,
                            category=trigger_channel.category,
                            reason=(
                                f"{member.display_name}"
                                " 建立的臨時語音頻道"
                            ),
                        )
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
                    log.exception(
                        "建立或移動臨時語音頻道時權限不足"
                    )

                except discord.HTTPException:
                    log.exception(
                        "建立或移動臨時語音頻道時發生 Discord API 錯誤"
                    )

                finally:
                    # 頻道建立成功但成員移動失敗時，
                    # 清理無主的空頻道。
                    if (
                        new_channel is not None
                        and (
                            member.voice is None
                            or member.voice.channel != new_channel
                        )
                    ):
                        self.temp_channel_ids.discard(new_channel.id)

                        try:
                            await new_channel.delete(
                                reason=(
                                    "成員未能移動至臨時語音頻道，"
                                    "清理孤兒頻道"
                                ),
                            )

                        except (
                            discord.NotFound,
                            discord.Forbidden,
                            discord.HTTPException,
                        ):
                            log.exception(
                                "清理孤兒臨時頻道失敗：%s",
                                new_channel.id,
                            )

        finally:
            # 即使等待 lock 或 API 呼叫被取消，
            # 也不能留下永久的建立鎖定。
            self._creating_for.discard(key)

    async def _delete_if_empty(
        self,
        channel: discord.VoiceChannel,
    ):
        """以鎖與短暫 debounce 降低多個離開事件造成的刪除競態。"""

        async with self._delete_lock:
            # 等待 Discord 的成員狀態更新完成，
            # 避免因事件順序造成誤判。
            await asyncio.sleep(0.25)

            if (
                channel.id not in self.temp_channel_ids
                or channel.members
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

            except discord.NotFound:
                # 頻道已經被刪除，不需要再處理。
                pass

            except (
                discord.Forbidden,
                discord.HTTPException,
            ):
                log.exception(
                    "刪除臨時語音頻道失敗：%s",
                    channel.id,
                )

            finally:
                self.temp_channel_ids.discard(channel.id)

    @tasks.loop(seconds=MUTE_CHECK_INTERVAL)
    async def check_afk_loop(self):
        now = time.monotonic()
        active_keys: set[tuple[int, int]] = set()

        for guild in self.bot.guilds:
            rest_channel = guild.get_channel(REST_CHANNEL_ID)

            # 複製清單，避免迴圈中 Discord 狀態更新造成競態。
            for channel in tuple(guild.voice_channels):
                if not self._is_temp_channel(channel):
                    continue

                for member in tuple(channel.members):
                    voice_state = member.voice
                    key = self._mute_key(member)

                    if (
                        voice_state is None
                        or voice_state.channel != channel
                    ):
                        self.mute_started_at.pop(key, None)
                        self._move_retry_at.pop(key, None)
                        continue

                    is_muted = (
                        voice_state.self_mute
                        or voice_state.mute
                    )

                    if not is_muted:
                        self.mute_started_at.pop(key, None)
                        self._move_retry_at.pop(key, None)
                        continue

                    active_keys.add(key)

                    # 理論上應該已由 voice state event 建立，
                    # 但這裡保留 fallback，避免 Bot 啟動時漏接事件。
                    started_at = self.mute_started_at.setdefault(
                        key,
                        now,
                    )

                    if now - started_at < MUTE_TIMEOUT:
                        continue

                    # 移動失敗時不要每 3 秒重複呼叫 Discord API。
                    if now < self._move_retry_at.get(key, 0.0):
                        continue

                    if not isinstance(
                        rest_channel,
                        discord.VoiceChannel,
                    ):
                        log.warning(
                            "找不到休息區語音頻道：%s",
                            REST_CHANNEL_ID,
                        )
                        continue

                    log.info(
                        "%s 已靜音超過 %d 秒，準備移動至休息區",
                        member,
                        int(MUTE_TIMEOUT),
                    )

                    moved = False

                    try:
                        # 輪詢期間可能已經改變狀態，
                        # 移動前再次確認。
                        if (
                            member.voice
                            and member.voice.channel == channel
                            and (
                                member.voice.self_mute
                                or member.voice.mute
                            )
                        ):
                            await member.move_to(
                                rest_channel,
                                reason=(
                                    "在臨時語音頻道靜音過久，"
                                    "自動移至休息區"
                                ),
                            )

                            moved = True

                            log.info(
                                "已將 %s 移至休息區",
                                member,
                            )

                    except discord.Forbidden:
                        self._move_retry_at[key] = (
                            now + MOVE_RETRY_INTERVAL
                        )

                        log.exception(
                            "移動 %s 至休息區時權限不足",
                            member,
                        )

                    except discord.HTTPException:
                        self._move_retry_at[key] = (
                            now + MOVE_RETRY_INTERVAL
                        )

                        log.exception(
                            "移動 %s 至休息區時發生 Discord API 錯誤",
                            member,
                        )

                    finally:
                        # 成功移動，或成員已離開/取消靜音時，
                        # 才清除計時。
                        #
                        # 暫時性的 API 或權限失敗則保留到期狀態，
                        # 等待下一次延遲重試。
                        if moved or not (
                            member.voice
                            and member.voice.channel == channel
                            and (
                                member.voice.self_mute
                                or member.voice.mute
                            )
                        ):
                            self.mute_started_at.pop(key, None)
                            self._move_retry_at.pop(key, None)

        # 清理已離開頻道、已被刪除，
        # 或已不再存在於本輪檢查的計時資料。
        for key in set(self.mute_started_at) - active_keys:
            self.mute_started_at.pop(key, None)
            self._move_retry_at.pop(key, None)

    @check_afk_loop.before_loop
    async def before_check_afk_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(TempVoiceCog(bot))
