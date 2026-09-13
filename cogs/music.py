import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp

# 設定 yt-dlp 參數：加入完整防護繞過與解碼設定（修正 js_runtimes 格式）
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
    'cookiefile': 'cookies.txt',  # 讀取伺服器根目錄下的 cookies.txt
    'js_runtimes': {'deno': {'path': '/home/ubuntu/.deno/bin/deno'}},
    'remote_components': {'ejs': 'github'},
    'extractor_args': {'youtube': {'client': ['tv']}},
}

# FFmpeg 參數：設定重新連線機制，避免因網路波動導致音樂中斷
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

class MusicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # 每個伺服器的播放佇列 {guild_id: [{"title": "歌名", "url": "網址", "stream_url": "串流網址"}]}
        self.queues = {}

    def get_queue(self, guild_id):
        if guild_id not in self.queues:
            self.queues[guild_id] = []
        return self.queues[guild_id]

    def play_next(self, interaction: discord.Interaction):
        """處理下一首歌的播放邏輯"""
        guild_id = interaction.guild_id
        voice_client = interaction.guild.voice_client
        queue = self.get_queue(guild_id)

        if len(queue) > 0:
            # 取出佇列中的第一首歌
            song = queue.pop(0)
            stream_url = song['stream_url']

            # 播放音訊，播放完畢後透過 callback 遞迴呼叫 play_next 播放下一首
            voice_client.play(
                discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS),
                after=lambda e: self.bot.loop.call_soon_threadsafe(self.play_next, interaction)
            )
            
            # 發送正在播放的通知
            asyncio.run_coroutine_threadsafe(
                interaction.channel.send(f"▶️ 正在播放：**{song['title']}**"),
                self.bot.loop
            )
        else:
            pass

    @app_commands.command(name="play", description="點播 YouTube 歌曲 (輸入關鍵字或網址)")
    @app_commands.describe(query="歌曲名稱或 YouTube 網址")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer() # 讀取 YouTube 資訊需要時間，先延遲回應避免超時

        if not interaction.user.voice:
            return await interaction.followup.send("❌ 你必須先加入語音頻道！")

        voice_channel = interaction.user.voice.channel
        voice_client = interaction.guild.voice_client

        # 如果機器人還沒進語音，就加入
        if not voice_client:
            voice_client = await voice_channel.connect()
        # 如果機器人在別的語音頻道
        elif voice_client.channel != voice_channel:
            return await interaction.followup.send("❌ 我已經在其他語音頻道為別人播歌囉！")

        # 透過 yt-dlp 搜尋/解析音樂
        loop = self.bot.loop
        try:
            # 移除強制 ytsearch 前綴，讓 default_search: 'auto' 自行判斷網址或關鍵字
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
            
            if 'entries' in data:
                # 如果是搜尋關鍵字，取第一個結果
                song_info = data['entries'][0]
            else:
                # 如果是直接貼網址
                song_info = data

            title = song_info.get('title')
            stream_url = song_info.get('url') # 真正的直連播放網址
            webpage_url = song_info.get('webpage_url')

        except Exception as e:
            return await interaction.followup.send(f"❌ 找不到這首歌或解析失敗：`{e}`")

        # 將歌曲加入該伺服器的佇列
        queue = self.get_queue(interaction.guild_id)
        queue.append({
            "title": title,
            "url": webpage_url,
            "stream_url": stream_url
        })

        if not voice_client.is_playing() and not voice_client.is_paused():
            # 如果目前沒有在播歌，立刻開始播放
            await interaction.followup.send(f"🎵 準備播放：**{title}**")
            self.play_next(interaction)
        else:
            # 如果已經在播歌，就只顯示加入佇列
            await interaction.followup.send(f"✅ 已加入佇列：**{title}** (目前佇列中還有 {len(queue)} 首歌)")

    @app_commands.command(name="skip", description="跳過當前播放的歌曲")
    async def skip(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.stop() 
            await interaction.response.send_message("⏭️ 已跳過當前歌曲！")
        else:
            await interaction.response.send_message("❌ 目前沒有正在播放的歌曲！", ephemeral=True)

    @app_commands.command(name="queue", description="查看目前的播放佇列")
    async def queue(self, interaction: discord.Interaction):
        queue = self.get_queue(interaction.guild_id)
        if not queue:
            return await interaction.response.send_message("📭 目前佇列是空的喔！")

        queue_text = ""
        for i, song in enumerate(queue):
            queue_text += f"**{i+1}.** {song['title']}\n"
        
        embed = discord.Embed(title="🎶 播放佇列", description=queue_text, color=discord.Color.blue())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="stop", description="停止播放並讓機器人離開語音頻道")
    async def stop(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if voice_client:
            if interaction.guild_id in self.queues:
                self.queues[interaction.guild_id].clear()
            
            await voice_client.disconnect()
            await interaction.response.send_message("👋 音樂已停止，我先退下啦！")
        else:
            await interaction.response.send_message("❌ 我不在語音頻道裡面喔！", ephemeral=True)

async def setup(bot):
    await bot.add_cog(MusicCog(bot))
