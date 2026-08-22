import asyncio
import discord
from discord.ext import commands, tasks

# ==================== 設定區 ====================
TRIGGER_CHANNEL_ID = 1510980890682200124  # 建立房間的觸發頻道 ID
REST_CHANNEL_ID = 1510980890682200124    # <- 請把這裡換成「睡眠區」或「休息區」的語音頻道 ID
# ================================================

class TempVoiceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.temp_channels = set()       # 記錄臨時頻道 ID
        self.afk_timers = {}             # 記錄使用者的掛機計時任務 {member_id: task}

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        # 1. 偵測使用者是否加入了「觸發建立頻道」
        if after.channel and after.channel.id == TRIGGER_CHANNEL_ID:
            guild = member.guild
            category = after.channel.category  

            channel_name = f"🔊 {member.display_name} 的房間"

            try:
                new_channel = await guild.create_voice_channel(
                    name=channel_name,
                    category=category,
                    reason=f"{member.display_name} 建立的臨時語音頻道"
                )
                await member.move_to(new_channel)
                self.temp_channels.add(new_channel.id)
            except discord.Forbidden:
                print("❌ 機器人權限不足，無法建立語音頻道或移動成員！")
            except Exception as e:
                print(f"❌ 建立臨時語音時發生錯誤: {e}")

        # 2. 掛機偵測邏輯：當使用者進入臨時頻道，且處於「靜音」或「離開/不動」狀態時開始計時
        # 這裡以「自己關閉麥克風 (self_mute)」或「被伺服器靜音」作為掛機判定範例
        if after.channel and after.channel.id in self.temp_channels:
            if after.self_mute or after.mute:
                # 如果開始掛機，啟動 10 分鐘（600秒）倒數計時
                if member.id not in self.afk_timers:
                    self.afk_timers[member.id] = self.bot.loop.create_task(self.afk_kick_task(member, after.channel))
            else:
                # 如果取消靜音，取消掛機計時
                if member.id in self.afk_timers:
                    self.afk_timers[member.id].cancel()
                    del self.afk_timers[member.id]

        # 3. 離開頻道時的清理與取消計時
        if before.channel and before.channel.id in self.temp_channels:
            # 取消該成員的掛機計時
            if member.id in self.afk_timers:
                self.afk_timers[member.id].cancel()
                del self.afk_timers[member.id]

            # 如果臨時頻道內沒人了，就自動刪除
            if len(before.channel.members) == 0:
                try:
                    await before.channel.delete(reason="臨時語音頻道已無人使用，自動清理")
                    self.temp_channels.remove(before.channel.id)
                except discord.HTTPException:
                    pass

    # 背景掛機計時任務函式
    async def afk_kick_task(self, member: discord.Member, channel: discord.VoiceChannel):
        try:
            # ⏳ 設定掛機時間：這裡設定為 600 秒 (10分鐘)，你可以自行更改秒數
            await asyncio.sleep(10)
            
            # 時間到後，檢查使用者是否還在該臨時頻道且依然處於靜音狀態
            if member.voice and member.voice.channel and member.voice.channel.id == channel.id:
                if member.voice.self_mute or member.voice.mute:
                    rest_channel = member.guild.get_channel(REST_CHANNEL_ID)
                    if rest_channel:
                        await member.move_to(rest_channel, reason="在臨時語音頻道掛機過久，自動移至休息區")
        except asyncio.CancelledError:
            # 如果使用者解除靜音或離開，計時任務被取消會進到這裡
            pass
        finally:
            if member.id in self.afk_timers:
                del self.afk_timers[member.id]

async def setup(bot):
    await bot.add_cog(TempVoiceCog(bot))
