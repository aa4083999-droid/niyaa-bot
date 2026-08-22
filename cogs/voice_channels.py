import asyncio
import discord
from discord.ext import commands, tasks

TRIGGER_CHANNEL_ID = 1510980890682200124  
REST_CHANNEL_ID = 1517983383052091523     

class TempVoiceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print("🚀 [極簡除錯版] 啟動！")
        self.debug_loop.start()

    def cog_unload(self):
        self.debug_loop.cancel()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if after.channel and after.channel.id == TRIGGER_CHANNEL_ID:
            print(f"✨ [事件觸發] {member.name} 進入了建立頻道！")
            guild = member.guild
            category = after.channel.category  
            channel_name = f"🔊 {member.display_name} 的房間"

            try:
                new_channel = await guild.create_voice_channel(
                    name=channel_name,
                    category=category,
                    reason="建立臨時語音"
                )
                await member.move_to(new_channel)
                print(f"✅ [成功建房並移動] {new_channel.name}")
            except Exception as e:
                print(f"❌ [建房失敗] {e}")

    @tasks.loop(seconds=3.0)
    async def debug_loop(self):
        print("🔍 [背景掃描中] 正在檢查伺服器頻道...")
        for guild in self.bot.guilds:
            print(f"🏠 伺服器: {guild.name} (ID: {guild.id})")
            for channel in guild.voice_channels:
                print(f"   📂 語音頻道: {channel.name} (ID: {channel.id}), 人數: {len(channel.members)}")
                for member in channel.members:
                    v = member.voice
                    mute_status = "未靜音"
                    if v and (v.self_mute or v.mute):
                        mute_status = "【已靜音】"
                    print(f"      👤 成員: {member.name} -> 狀態: {mute_status}")

    @debug_loop.before_loop
    async def before_debug_loop(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(TempVoiceCog(bot))
