import asyncio
import discord
from discord.ext import commands, tasks

TRIGGER_CHANNEL_ID = 1510980890682200124  
REST_CHANNEL_ID = 1517983383052091523     

class TempVoiceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.mute_durations = {}  # 記錄每個成員連續靜音的秒數 {member_id: seconds}
        print("🚀 [Debug v3] TempVoiceCog 模組（掃描迴圈版）已初始化！")
        self.check_afk_loop.start()

    def cog_unload(self):
        self.check_afk_loop.cancel()

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

        # 2. 空房自動清理（當有人離開某個臨時頻道時檢查）
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

    # 每 3 秒背景自動掃描一次所有臨時房間的靜音狀態
    @tasks.loop(seconds=3.0)
    async def check_afk_loop(for_test=None):
        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                if "的房間" in channel.name and channel.id != TRIGGER_CHANNEL_ID:
                    for member in channel.members:
                        # 檢查是否處於靜音 (self_mute 或 server mute)
                        if member.voice and (member.voice.self_mute or member.voice.mute):
                            # 累積秒數
                            self.mute_durations[member.id] = self.mute_durations.get(member.id, 0) + 3
                            print(f"⏱️ 成員 {member.name} 在臨時房靜音中... 已累積 {self.mute_durations[member.id]} 秒")

                            # 超過 10 秒（測試用）就移走
                            if self.mute_durations[member.id] >= 10:
                                rest_channel = guild.get_channel(REST_CHANNEL_ID)
                                if rest_channel:
                                    try:
                                    await member.move_to(rest_channel, reason="在臨時語音頻道掛機過久，自動移至休息區")
                                        print(f"🚀 [掃描成功] 已將掛機成員 {member.name} 移至休息區！")
                                    except Exception as e:
                                        print(f"❌ 移動成員失敗: {e}")
                                else:
                                    print(f"❌ 找不到休息區頻道 ID: {REST_CHANNEL_ID}")
                                
                                # 移走後清空計數
                                self.mute_durations[member.id] = 0
                        else:
                            # 如果沒有靜音，清空他的計數
                            if member.id in self.mute_durations:
                                self.mute_durations[member.id] = 0

    @check_afk_loop.before_loop
    async def before_check_afk_loop(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(TempVoiceCog(bot))
