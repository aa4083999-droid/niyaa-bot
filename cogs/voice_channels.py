import asyncio
import discord
from discord.ext import commands

TRIGGER_CHANNEL_ID = 1510980890682200124  
REST_CHANNEL_ID = 1517983383052091523     

class TempVoiceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.temp_channels = set()       
        self.afk_timers = {}             
        print("🚀 [Debug] TempVoiceCog 模組已成功初始化載入！")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        # 只要有人在伺服器裡有任何語音動作，這裡就一定會印出名字
        print(f"🎤 [Debug 語音事件] 成員 {member.name} 觸發了語音狀態更新")

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
                self.temp_channels.add(new_channel.id)
                print(f"✅ 成功建立並移動至新房間: {new_channel.name}")
            except Exception as e:
                print(f"❌ 建立臨時語音時發生錯誤: {e}")

        # 2. 掛機偵測
        if after.channel and after.channel.id in self.temp_channels:
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

        # 3. 離開頻道
        if before.channel and before.channel.id in self.temp_channels:
            if member.id in self.afk_timers:
                self.afk_timers[member.id].cancel()
                del self.afk_timers[member.id]

            if len(before.channel.members) == 0:
                try:
                    await before.channel.delete(reason="臨時語音頻道已無人使用，自動清理")
                    self.temp_channels.remove(before.channel.id)
                    print(f"🗑️ 臨時頻道已刪除")
                except Exception:
                    pass

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
            print(f"❌ 掛機計時被取消（可能使用者取消靜音或離開了）")
        finally:
            if member.id in self.afk_timers:
                del self.afk_timers[member.id]

async def setup(bot):
    await bot.add_cog(TempVoiceCog(bot))
