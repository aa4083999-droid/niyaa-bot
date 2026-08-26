import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
import tempfile
import time

import discord
from discord.ext import commands, tasks

log = logging.getLogger(__name__)

TRIGGER_CHANNEL_ID = 1510980890682200124
REST_CHANNEL_ID = 1517983383052091523

# 設定：3 秒輪詢，30 分鐘靜音門檻（正式版設定）
MUTE_CHECK_INTERVAL = 3.0
MUTE_TIMEOUT = 30.0 * 60.0  # 30 分鐘
# 移動/刪除失敗時的重試冷卻時間（15 秒）
RETRY_COOLDOWN = 15.0

TEMP_CHANNEL_PREFIX = "🔊 "
DATA_FILE = "data/temp_voice_channels.json"


class TempVoiceCog(commands.Cog):
    """建立臨時語音頻道，並將長時間靜音的成員移至休息區（具備嚴密防護與原子化持久化）。"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # 使用 monotonic 時鐘記錄開始靜音時間，避免系統時間調整影響計時。
        self.mute_started_at: dict[tuple[int, int], float] = {}

        # 記錄移動失敗的冷卻時間點 { (guild_id, member_id): monotonic_timestamp }
        self.move_failed_at: dict[tuple[int, int], float] = {}

        # 記錄頻道刪除失敗的冷卻時間點 { channel_id: monotonic_timestamp }
        self.channel_delete_failed_at: dict[int, float] = {}

        # 記錄正在執行刪除任務的頻道 ID，防止重複排程
        self._deleting_channel_ids: set[int] = set()

        # 記錄本 Cog 管理的臨時頻道 ID 集合
        self.temp_channel_ids: set[int] = set()

        # 避免同時建立多個 Discord 頻道
        self._create_lock = asyncio.Lock()

        # 避免多個離開事件同時刪除同一個頻道
        self._delete_lock = asyncio.Lock()

        # 防止同一位使用者因 Gateway 重複事件重複建立房間
        self._creating_for: set[tuple[int, int]] = set()

        # 持久化寫入相關控制 (Debounce & Background Thread)
        self._save_lock = asyncio.Lock()
        self._save_task: asyncio.Task | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="TempVoiceSave")

        # 載入持久化資料
        self._load_persisted_channels()

        self.check_afk_loop.start()
        log.info(
            "TempVoiceCog 已啟動（輪詢間隔：%.1f秒 / 靜音門檻：%.1f分鐘）",
            MUTE_CHECK_INTERVAL,
            MUTE_TIMEOUT / 60.0,
        )

    def cog_unload(self):
        self.check_afk_loop.cancel()
        if self._save_task and not self._save_task.done():
            self._save_task.cancel()
        self._executor.shutdown(wait=False)

    # --- 持久化輔助方法 (防抖 + 暫存檔原子替換 + 背景執行緒) ---

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

    def _save_sync(self, channel_ids_list: list[int]):
        """在背景執行緒中透過暫存檔安全寫入資料，避免阻塞主迴圈"""
        temp_name = None
        try:
            self._ensure_data_dir()
            dir_name = os.path.dirname(DATA_FILE)
            with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tf:
                json.dump(channel_ids_list, tf, ensure_ascii=False, indent=2)
                temp_name = tf.name
            os.replace(temp_name, DATA_FILE)
        except Exception:
            log.exception("儲存暫存頻道持久化檔案失敗")
        finally:
            if temp_name and os.path.exists(temp_name):
                try:
                    os.remove(temp_name)
                except Exception:
                    pass

    async def _save_persisted_channels(self):
        """帶有 2 秒 Debounce 機制的非同步儲存排程"""
        async with self._save_lock:
            if self._save_task and not self._save_task.done():
                self._save_task.cancel()
            
            async def debounced_save():
                await asyncio.sleep(2.0)
                channel_list = list(self.temp_channel_ids)
                await asyncio.get_running_loop().run_in_executor(
                    self._executor, self._save_sync, channel_list
                )

            self._save_task = asyncio.create_task(debounced_save())

    def _is_temp_channel(
        self,
        channel: discord.abc.GuildChannel | None,
    ) -> bool:
        if channel is None or channel.id in (TRIGGER_CHANNEL_ID, REST_CHANNEL_ID):
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
            self._deleting_channel_ids.discard(channel.id)
            await self._save_persisted_channels()

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
            now = time.monotonic()
            last_fail = self.channel_delete_failed_at.get(before.channel.id, 0.0)
            if (
                before.channel.id not in self._deleting_channel_ids
                and now - last_fail >= RETRY_COOLDOWN
                and len(before.channel.members) == 0
            ):
                self._deleting_channel_ids.add(before.channel.id)
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
        new_channel: discord.VoiceChannel | None = None
        move_succeeded = False

        try:
            async with self._create_lock:
                if (
                    member.voice is None
                    or member.voice.channel != trigger_channel
                ):
                    return

                channel_name = f"{TEMP_CHANNEL_PREFIX}{member.display_name} 的房間"
                
                new_channel = await member.guild.create_voice_channel(
                    name=channel_name,
                    category=trigger_channel.category,
                    reason=f"{member.display_name} 建立的臨時語音頻道",
                )

                self.temp_channel_ids.add(new_channel.id)
                await self._save_persisted_channels()

                await member.move_to(
                    new_channel,
                    reason="移動至新建立的臨時語音頻道",
                )

                move_succeeded = True

                log.info(
                    "已建立臨時語音頻道：%s (%s)",
                    new_channel.name,
                    new_channel.id,
                )

        except discord.Forbidden:
            log.error("建立或移動臨時語音頻道時權限不足 (Forbidden)")
        except discord.HTTPException:
            log.exception("建立或移動臨時語音頻道時發生 Discord API 錯誤")
        except Exception:
            log.exception("建立臨時頻道時發生未預期錯誤")
        finally:
            self._creating_for.discard(key)

            # 依據明確的 API 成功旗標判定，完全避開 member.voice 快取競態問題
            if new_channel is not None and not move_succeeded:
                self.temp_channel_ids.discard(new_channel.id)
                self._deleting_channel_ids.discard(new_channel.id)
                await self._save_persisted_channels()
                try:
                    await new_channel.delete(
                        reason="成員未能移動至臨時語音頻道，清理孤兒頻道",
                    )
                    log.info("已安全清理孤兒臨時頻道：%s", new_channel.id)
                except (
                    discord.NotFound,
                    discord.Forbidden,
                    discord.HTTPException,
                ):
                    log.exception("清理孤兒臨時頻道失敗：%s", new_channel.id)

    async def _delete_if_empty(
        self,
        channel: discord.VoiceChannel,
    ):
        now = time.monotonic()
        last_fail = self.channel_delete_failed_at.get(channel.id, 0.0)
        if now - last_fail < RETRY_COOLDOWN:
            self._deleting_channel_ids.discard(channel.id)
            return

        async with self._delete_lock:
            await asyncio.sleep(0.5)

            if (
                channel.id not in self.temp_channel_ids
                or len(channel.members) > 0
            ):
                self._deleting_channel_ids.discard(channel.id)
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
                self.channel_delete_failed_at.pop(channel.id, None)
                await self._save_persisted_channels()
            except discord.NotFound:
                self.temp_channel_ids.discard(channel.id)
                self.channel_delete_failed_at.pop(channel.id, None)
                await self._save_persisted_channels()
            except discord.Forbidden:
                self.channel_delete_failed_at[channel.id] = time.monotonic()
                log.error("刪除臨時語音頻道失敗：權限不足 (%s)", channel.id)
            except discord.HTTPException:
                self.channel_delete_failed_at[channel.id] = time.monotonic()
                log.exception("刪除臨時語音頻道失敗：%s", channel.id)
            finally:
                self._deleting_channel_ids.discard(channel.id)

    @tasks.loop(seconds=MUTE_CHECK_INTERVAL)
    async def check_afk_loop(self):
        now = time.monotonic()
        active_keys: set[tuple[int, int]] = set()
        stale_channel_ids: set[int] = set()

        for cid in list(self.temp_channel_ids):
            try:
                ch = self.bot.get_channel(cid)
                
                if ch is None or not isinstance(ch, discord.VoiceChannel):
                    stale_channel_ids.add(cid)
                    continue

                if len(ch.members) == 0:
                    last_fail = self.channel_delete_failed_at.get(cid, 0.0)
                    if (
                        cid not in self._deleting_channel_ids
                        and now - last_fail >= RETRY_COOLDOWN
                    ):
                        self._deleting_channel_ids.add(cid)
                        asyncio.create_task(self._delete_if_empty(ch))
                    continue

                rest_channel = ch.guild.get_channel(REST_CHANNEL_ID)

                for member in ch.members:
                    try:
                        voice_state = member.voice
                        key = self._mute_key(member)

                        if (
                            voice_state is None
                            or voice_state.channel != ch
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

                        last_fail = self.move_failed_at.get(key, 0.0)
                        if now - last_fail < RETRY_COOLDOWN:
                            continue

                        if not isinstance(rest_channel, discord.VoiceChannel):
                            continue

                        if (
                            member.voice
                            and member.voice.channel == ch
                            and (member.voice.self_mute or member.voice.mute)
                        ):
                            try:
                                await member.move_to(
                                    rest_channel,
                                    reason="在臨時語音頻道靜音過久，自動移至休息區",
                                )
                                log.info("已將長時間靜音成員 %s 移至休息區", member)
                                self.mute_started_at.pop(key, None)
                                self.move_failed_at.pop(key, None)
                            except (discord.Forbidden, discord.HTTPException) as e:
                                self.move_failed_at[key] = now
                                log.warning("移動成員 %s 至休息區失敗（HTTP/Forbidden）：%s", member, e)
                                continue

                    except discord.Forbidden:
                        log.error("移動 %s 至休息區時權限不足", member)
                    except discord.HTTPException:
                        log.exception("移動 %s 至休息區時發生 API 錯誤", member)
                    except Exception:
                        log.exception("檢核成員 AFK 狀態時發生未預期錯誤")

            except Exception:
                log.exception("檢核臨時頻道 ID %s 時發生未預期錯誤", cid)
                continue

        # 使用 fetch_channel 進行網路級別的真正確認，避免本地快取暫時查不到而誤刪有效頻道
        if stale_channel_ids:
            for cid in stale_channel_ids:
                try:
                    channel_obj = await self.bot.fetch_channel(cid)
                    if isinstance(channel_obj, discord.VoiceChannel):
                        # 其實有找到，代表剛剛只是快取暫時漏掉，放回集合中
                        continue
                except discord.NotFound:
                    log.warning("經 fetch_channel 確認，暫存頻道 %s 已被刪除，清除追蹤。", cid)
                    self.temp_channel_ids.discard(cid)
                    self._deleting_channel_ids.discard(cid)
                except discord.Forbidden:
                    log.warning("經 fetch_channel 確認，對頻道 %s 權限不足，暫時保留追蹤。", cid)
                except discord.HTTPException:
                    log.warning("經 fetch_channel 確認發生 API 異常，暫存頻道 %s 暫時保留。", cid)
            await self._save_persisted_channels()

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

        valid_ids = set()
        for cid in list(self.temp_channel_ids):
            channel = self.bot.get_channel(cid)
            if isinstance(channel, discord.VoiceChannel):
                valid_ids.add(cid)
                if len(channel.members) == 0:
                    now = time.monotonic()
                    last_fail = self.channel_delete_failed_at.get(cid, 0.0)
                    if (
                        cid not in self._deleting_channel_ids
                        and now - last_fail >= RETRY_COOLDOWN
                    ):
                        self._deleting_channel_ids.add(cid)
                        asyncio.create_task(self._delete_if_empty(channel))
            else:
                # 啟動時使用 fetch 驗證，避免快取未同步造成誤刪
                try:
                    channel_obj = await self.bot.fetch_channel(cid)
                    if isinstance(channel_obj, discord.VoiceChannel):
                        valid_ids.add(cid)
                        if len(channel_obj.members) == 0:
                            now = time.monotonic()
                            last_fail = self.channel_delete_failed_at.get(cid, 0.0)
                            if (
                                cid not in self._deleting_channel_ids
                                and now - last_fail >= RETRY_COOLDOWN
                            ):
                                self._deleting_channel_ids.add(cid)
                                asyncio.create_task(self._delete_if_empty(channel_obj))
                    else:
                        log.warning("啟動時發現持久化 ID %s 不是語音頻道，將予以清理。", cid)
                except discord.NotFound:
                    log.warning("啟動時確認持久化頻道 ID %s 已不存在，將予以清理。", cid)
                except Exception:
                    # 若網路異常或 API 限流，先保留避免重啟時誤刪
                    valid_ids.add(cid)
                    log.warning("啟動時驗證頻道 %s 發生異常，暫時保留。", cid)

        if valid_ids != self.temp_channel_ids:
            log.warning("啟動時清理了失效的暫存頻道。原數量: %d, 有效數量: %d", len(self.temp_channel_ids), len(valid_ids))
            self.temp_channel_ids = valid_ids
            await self._save_persisted_channels()

        # 檢查 Trigger 頻道
        trigger_channel = self.bot.get_channel(TRIGGER_CHANNEL_ID)
        if not isinstance(trigger_channel, discord.VoiceChannel):
            log.warning(
                "【注意】指定的 TRIGGER_CHANNEL_ID (%s) 無效或不是語音頻道！",
                TRIGGER_CHANNEL_ID,
            )
        else:
            permissions = trigger_channel.permissions_for(trigger_channel.guild.me)
            if not permissions.manage_channels or not permissions.move_members:
                log.error("【嚴重警告】機器人在 Trigger 頻道缺少 '管理頻道 (Manage Channels)' 或 '移動成員 (Move Members)' 權限！")

        # 檢查 Rest 頻道
        rest_channel = self.bot.get_channel(REST_CHANNEL_ID)
        if not isinstance(rest_channel, discord.VoiceChannel):
            log.warning(
                "【注意】指定的 REST_CHANNEL_ID (%s) 無效或不是語音頻道，長時間靜音移動功能將無法運作！",
                REST_CHANNEL_ID,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(TempVoiceCog(bot))
