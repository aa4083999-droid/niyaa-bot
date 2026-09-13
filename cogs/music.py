import asyncio
import discord
from discord import app_commands
from discord.ext import commands, tasks
import yt_dlp

# 設定 yt-dlp 參數：維持最強防護與解碼設定
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'cookiefile': 'cookies.txt',
    'js_runtimes': {'deno': {'path': '/home/ubuntu/.deno/bin/deno'}},
    'remote_components': {'ejs': 'github'},
    'extractor_args': {'youtube': {'client': ['tv']}},
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

class AdvancedMusicControlView(discord.ui.View):
    def __init__(self, cog, guild_id):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

    @discord.ui.button(label="暫停/繼續", style=discord.ButtonStyle.primary, emoji="⏯️")
    async def toggle_pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("❌ 機器人未連線！", ephemeral=True)
        if vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ 已暫停播放。", ephemeral=True)
        elif vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ 恢復播放！", ephemeral=True)
        else:
            await interaction.response.send_message("❌ 目前沒有在播放音樂。", ephemeral=True)

    @discord.ui.button(label="跳過", style=discord.ButtonStyle.secondary, emoji="⏭️")
    async def skip_song(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            await interaction.response.send_message("⏭️ 已跳過當前歌曲！", ephemeral=True)
        else:
            await interaction.response.send_message("❌ 目前沒有正在播放的歌曲！", ephemeral=True)

    @discord.ui.button(label="佇列", style=discord.ButtonStyle.success, emoji="📋")
    async def show_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        queue = self.cog.get_queue(self.guild_id)
        if not queue:
            return await interaction.response.send_message("📭 目前佇列是空的喔！", ephemeral=True)
        queue_text = "".join(f"**{i+1}.** {song['title']}\n" for i, song in enumerate(queue[:10]))
        embed = discord.Embed(title="🎶 目前播放佇列", description=queue_text, color=discord.Color.brand_green())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="中斷連線", style=discord.ButtonStyle.danger, emoji="👋")
    async def stop_bot(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc:
            if self.guild_id in self.cog.queues:
                self.cog.queues[self.guild_id].clear()
            await vc.disconnect()
            await interaction.response.send_message("👋 音樂已停止，機器人已退出語音頻道！", ephemeral=True)
        else:
            await interaction.response.send_message("❌ 機器人不在語音頻道中！", ephemeral=True)

class MusicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {}
        self.volumes = {} 
        self.idle_check.start()

    def cog_unload(self):
        self.idle_check.cancel()

    def get_queue(self, guild_id):
        if guild_id not in self.queues:
            self.queues[guild_id] = []
        return self.queues[guild_id]

    def get_volume(self, guild_id):
        return self.volumes.get(guild_id, 0.5)

    @tasks.loop(minutes=1.0)
    async def idle_check(self):
        for guild in self.bot.guilds:
            vc = guild.voice_client
            if vc and vc.is_connected():
                if len(vc.channel.members) == 1:
                    if guild.id in self.queues:
                        self.queues[guild.id].clear()
                    await vc.disconnect()

    @idle_check.before_loop
    async def before_idle_check(self):
        await self.bot.wait_until_ready()

    def play_next(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        voice_client = interaction.guild.voice_client
        queue = self.get_queue(guild_id)

        if voice_client and not voice_client.is_connected():
            return

        if len(queue) > 0:
            song = queue.pop(0)
            stream_url = song['stream_url']
            volume = self.get_volume(guild_id)

            audio_source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
            transformed_source = discord.PCMVolumeTransformer(audio_source, volume=volume)

            voice_client.play(
                transformed_source,
                after=lambda e: self.bot.loop.call_soon_threadsafe(self.play_next, interaction)
            )
            
            # 仿照大廠機器人的美觀 Embed 介面與按鈕
            embed = discord.Embed(
                title="🎶 正在播放音樂",
                description=f"[{song['title']}]({song['url']})\n\n⏳ 狀態：播放中",
                color=discord.Color.blurple()
            )
            embed.set_footer(text=f"音量: {int(volume*100)}% | 點歌者服務中")

            view = AdvancedMusicControlView(self, guild_id)
            asyncio.run_coroutine_threadsafe(
                interaction.channel.send(embed=embed, view=view),
                self.bot.loop
            )

    @app_commands.command(name="play", description="點播 YouTube 歌曲 (支援關鍵字或網址)")
    @app_commands.describe(query="歌曲名稱或網址")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()

        if not interaction.user.voice:
            return await interaction.followup.send("❌ 你必須先加入語音頻道！")

        voice_channel = interaction.user.voice.channel
        voice_client = interaction.guild.voice_client

        if not voice_client:
            voice_client = await voice_channel.connect()
        elif voice_client.channel != voice_channel:
            return await interaction.followup.send("❌ 我已經在其他語音頻道服務囉！")

        loop = self.bot.loop
        try:
            # 透過多執行緒非同步提取，縮短等待感受
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
            song_info = data['entries'][0] if 'entries' in data else data

            title = song_info.get('title')
            stream_url = song_info.get('url')
            webpage_url = song_info.get('webpage_url')
        except Exception as e:
            return await interaction.followup.send(f"❌ 找不到這首歌或解析失敗：`{e}`")

        queue = self.get_queue(interaction.guild_id)
        queue.append({"title": title, "url": webpage_url, "stream_url": stream_url})

        if not voice_client.is_playing() and not voice_client.is_paused():
            await interaction.followup.send(f"🎵 成功解析，準備播放：**{title}**")
            self.play_next(interaction)
        else:
            embed = discord.Embed(
                title="✅ 已加入播放佇列",
                description=f"[{title}]({webpage_url})",
                color=discord.Color.green()
            )
            embed.set_footer(text=f"目前佇列中還有 {len(queue)} 首歌")
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="volume", description="調整音樂播放音量 (0 - 100)")
    @app_commands.describe(level="音量大小 (0 到 100)")
    async def volume(self, interaction: discord.Interaction, level: int):
        if not 0 <= level <= 100:
            return await interaction.response.send_message("❌ 音量必須介於 0 到 100 之間！", ephemeral=True)
        
        guild_id = interaction.guild_id
        vol_float = level / 100.0
        self.volumes[guild_id] = vol_float

        vc = interaction.guild.voice_client
        if vc and vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = vol_float

        await interaction.response.send_message(f"🔊 音量已調整為：**{level}%**")

    @app_commands.command(name="pause", description="暫停目前播放的音樂")
    async def pause(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ 音樂已暫停！")
        else:
            await interaction.response.send_message("❌ 目前沒有正在播放的音樂！", ephemeral=True)

    @app_commands.command(name="resume", description="恢復播放暫停的音樂")
    async def resume(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ 恢復播放音樂！")
        else:
            await interaction.response.send_message("❌ 目前音樂沒有處於暫停狀態！", ephemeral=True)

    @app_commands.command(name="skip", description="跳過當前播放的歌曲")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            await interaction.response.send_message("⏭️ 已跳過當前歌曲！")
        else:
            await interaction.response.send_message("❌ 目前沒有正在播放的歌曲！", ephemeral=True)

    @app_commands.command(name="queue", description="查看目前的播放佇列")
    async def queue_cmd(self, interaction: discord.Interaction):
        queue = self.get_queue(interaction.guild_id)
        if not queue:
            return await interaction.response.send_message("📭 目前佇列是空的喔！")

        queue_text = "".join(f"**{i+1}.** {song['title']}\n" for i, song in enumerate(queue[:15]))
        embed = discord.Embed(title="🎶 播放佇列", description=queue_text, color=discord.Color.blue())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="stop", description="停止播放並讓機器人離開語音頻道")
    async def stop(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc:
            if interaction.guild_id in self.queues:
                self.queues[interaction.guild_id].clear()
            await vc.disconnect()
            await interaction.response.send_message("👋 音樂已停止，我先退下啦！")
        else:
            await interaction.response.send_message("❌ 我不在語音頻道裡面喔！", ephemeral=True)

async def setup(bot):
    await bot.add_cog(MusicCog(bot))
