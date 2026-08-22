import asyncio
import discord
from discord.ext import commands

TRIGGER_CHANNEL_ID = 1510980890682200124  
REST_CHANNEL_ID = 1517983383052091523     

class TempVoiceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.afk_timers = {}             
        print("🚀 [Debug v2] TempVoiceCog 模組已成功初始化載入！")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        # 1. 偵測使用者是否加入了「觸發建立房間」
        if after.channel and after.channel.id == TRIGGER_CHANNEL_ID:
            print(f"✨ 偵測到使用者進入建立頻道: {member.name}")
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
                print(f"✅ 成功建立並移動至新房間: {new_channel.name}")
            except Exception as e:
                print(f"❌ 建立臨時語音時發生錯誤: {e}")
            return

        # 判定是否為臨時房間（只要頻道名稱包含 "的房間" 且不是觸發頻道，就視為臨時房）
        def is_temp_channel(channel):
            if not channel:
                return False
            return "的房間" in channel.name and channel.id != TRIGGER_CHANNEL_ID

        # 2. 掛機偵測（只要在臨時頻道內，且處於靜音狀態）
        if is_temp_channel(after.channel):
            print(f"🔍 成員在臨時頻道內，目前狀態 - self_mute: {after.self_mute}, mute: {after.mute}")
            if after.self_mute or after.mute:
                if member.id not in self.afk_timers:
                    print(f"⏱️ 成員 {member.name} 開始靜音，啟動 10 秒掛機倒數...")
                    self.afk_timers[member.id] = self.bot.loop.create_task(self.afk_kick_task(member, after.channel))
            else:
                if member.id in self.afk_timers:
                    print(f"⚡ 成員取消靜音，取消掛機計時。")
                    self.afk_timers[member.id].cancel()
                    del self.afk_timers[member.id]

        # 3. 離開頻道或切換頻道時清理計時與空房刪除
        if is_temp_channel(before.channel):
            if member.id in self.afk_timers:
                self.afk_timers[member.id].cancel()
                del self.afk_timers[member.id]

            if len(before.channel.members) == 0:
                try:
                    await before.channel.delete(reason="臨時語音頻道已無人使用，自動清理")
                    print(f"🗑️ 空臨時頻道已刪除: {before.channel.name}")
                except Exception as e:
                    print(f"❌ 刪除頻道失敗: {e}")

    async def afk_kick_task(self, member: discord.Member, channel: discord.VoiceChannel):
        try:
            await asyncio.sleep(10)
            print(f"⏰ 倒數 10 秒時間到！檢查 {member.name} 是否仍在頻道且靜音...")
            
            if member.voice and member.voice.channel and member.voice.channel.id == channel.id:
                if member.voice.self_mute or member.voice.mute:
                    rest_channel = member.guild.get_channel(REST_CHANNEL_ID)
                    if rest_channel:
                        await member.move_to(rest_channel, reason="在臨時語音頻道掛機過久，自動移至休息區")
                        print(f"🚀 成功將掛機成員 {member.name} 移至休息區！")
                    else:
                        print(f"❌ 找不到休息區頻道 ID: {REST_CHANNEL_ID}")
        except asyncio.CancelledError:
            print(f"❌ 掛機計時被取消")
        finally:
            if member.id in self.afk_timers:
                del self.afk_timers[member.id]

async def setup(bot):
    await bot.add_cog(TempVoiceCog(bot))
