import asyncio
from datetime import datetime, timezone
from ytmusicapi import YTMusic
from src.logger import get_logger
from .base_fetcher import BaseFetcher

logger = get_logger("youtube_fetcher")

class YoutubeFetcher(BaseFetcher):
    def __init__(self):
        self.ytmusic = None
    
    def _get_ytmusic(self):
        """Lazy initialize YTMusic instance (not async as YTMusic doesn't support it)"""
        if self.ytmusic is None:
            self.ytmusic = YTMusic()
        return self.ytmusic
    
    async def fetch(self, artist: str, song: str, timestamps: bool = False):
        """Async fetch from YouTube Music API"""
        try:
            logger.info(f"Attempting YouTube Music API for {artist} - {song}")
            
            # Run blocking YTMusic calls in thread pool to avoid blocking event loop
            ytmusic = self._get_ytmusic()
            
            # Search for song
            search_query = f"{song} {artist}"
            loop = asyncio.get_event_loop()
            search_results = await loop.run_in_executor(
                None,
                lambda: ytmusic.search(query=search_query, filter="songs", limit=1)
            )
            
            if not search_results:
                return None
            
            video_id = search_results[0].get("videoId")
            if not video_id:
                return None
            
            # Get watch playlist
            watch_playlist = await loop.run_in_executor(
                None,
                lambda: ytmusic.get_watch_playlist(videoId=video_id)
            )
            
            lyrics_browse_id = watch_playlist.get("lyrics")
            if not lyrics_browse_id:
                return None
            
            # Get lyrics
            lyrics_data = await loop.run_in_executor(
                None,
                lambda: ytmusic.get_lyrics(browseId=lyrics_browse_id)
            )
            
            if not lyrics_data or not lyrics_data.get("lyrics"):
                return None
            
            timed_lyrics = None
            if lyrics_data.get("hasTimestamps"):
                try:
                    timed_lyrics = [
                        {
                            "text": line.text,
                            "start_time": getattr(line, "start_time", None),
                            "end_time": getattr(line, "end_time", None),
                            "id": getattr(line, "line_id", None)
                        }
                        for line in lyrics_data["lyrics"]
                    ]
                except Exception as e:
                    logger.warning(f"Failed to parse timed lyrics: {e}")
                    pass
            
            result = {
                "source": "youtube_music",
                "artist": artist,
                "title": song,
                "lyrics": "\n".join(
                    line.text for line in lyrics_data["lyrics"]
                ) if hasattr(lyrics_data["lyrics"][0], "text") else lyrics_data["lyrics"],
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            }
            
            if timed_lyrics:
                result["timed_lyrics"] = timed_lyrics
                result["hasTimestamps"] = True
            
            return result
        
        except Exception as e:
            logger.error(f"YouTube Music API error: {e}")
            return None