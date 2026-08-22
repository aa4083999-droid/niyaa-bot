import asyncio
import discord
from discord.ext import commands, tasks

TRIGGER_CHANNEL_ID = 1510980890682200124  
REST_CHANNEL_ID = 1517983383052091523     

class TempVoiceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.mute_durations = {}  
        print("🚀 [正式完整版] TempVoiceCog 已啟動")
        self.check_afk_loop.start()

    def cog_unload(self):
        self.check_afk_loop.cancel()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
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

        def is_temp_channel(channel):
            if not channel:
                return False
            return "的房間" in channel.name and channel.id != TRIGGER_CHANNEL_ID

        if is_temp_channel(before.channel):
            if len(before.channel.members) == 0:
                try:
                    await before.channel.delete(reason="臨時語音頻道已無人使用，自動清理")
                    print(f"🗑️ 空臨時頻道已刪除: {before.channel.name}")
                except Exception as e:
                    print(f"❌ 刪除頻道失敗: {e}")

    @tasks.loop(seconds=3.0)
    async def check_afk_loop(self):
        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                if "的房間" in channel.name and channel.id != TRIGGER_CHANNEL_ID:
                    for member in channel.members:
                        v = member.voice
                        if v:
                            if v.self_mute or v.mute:
                                self.mute_durations[member.id] = self.mute_durations.get(member.id, 0) + 3
                                print(f"⏱️ {member.name} 靜音中，累計秒數: {self.mute_durations[member.id]}")

                                if self.mute_durations[member.id] >= 10:  # 測試用 10 秒
                                    rest_channel = guild.get_channel(REST_CHANNEL_ID)
                                    if rest_channel:
                                        try:
                                            await member.move_to(rest_channel, reason="在臨時語音頻道掛機過久，自動移至休息區")
                                            print(f"🚀 [成功移動] 已將 {member.name} 移至休息區！")
                                        except Exception as e:
                                            print(f"❌ [移動失敗] 報錯原因: {e}")
                                    else:
                                        print(f"❌ 找不到休息區頻道 ID: {REST_CHANNEL_ID}")
                                    
                                    self.mute_durations[member.id] = 0
                            else:
                                if member.id in self.mute_durations and self.mute_durations[member.id] > 0:
                                    print(f"🔄 {member.name} 解除靜音，重置計數")
                                    self.mute_durations[member.id] = 0

    @check_afk_loop.before_loop
    async def before_check_afk_loop(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(TempVoiceCog(bot))
