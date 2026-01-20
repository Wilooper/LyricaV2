import asyncio
from datetime import datetime, timezone
from src.config import GENIUS_TOKEN
from src.logger import get_logger
from .base_fetcher import BaseFetcher
from lyricsgenius import Genius

logger = get_logger("genius_fetcher")

class GeniusFetcher(BaseFetcher):
    def __init__(self, token: str = GENIUS_TOKEN):
        self.token = token
        self.genius = None
    
    def _get_genius(self):
        """Lazy initialize Genius instance (not async as lyricsgenius doesn't support it)"""
        if self.genius is None and self.token:
            self.genius = Genius(
                self.token,
                skip_non_songs=True,
                remove_section_headers=True,
                verbose=False
            )
        return self.genius
    
    async def fetch(self, artist: str, song: str, timestamps: bool = False):
        """Async fetch from Genius API"""
        if not self.token:
            logger.info("Genius token not configured.")
            return None
        
        try:
            logger.info(f"Attempting Genius for {artist} - {song}")
            
            # Run blocking Genius calls in thread pool
            genius = self._get_genius()
            if not genius:
                return None
            
            loop = asyncio.get_event_loop()
            g_song = await loop.run_in_executor(
                None,
                lambda: genius.search_song(song, artist)
            )
            
            if g_song and getattr(g_song, "lyrics", None):
                return {
                    "source": "genius",
                    "artist": g_song.artist,
                    "title": g_song.title,
                    "lyrics": g_song.lyrics,
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                }
            
            return None
        
        except Exception as e:
            logger.error(f"Genius API error: {e}")
            return None