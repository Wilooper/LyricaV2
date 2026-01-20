import httpx
from datetime import datetime, timezone
from src.logger import get_logger
from .base_fetcher import BaseFetcher

logger = get_logger("lyricsovh_fetcher")

class LyricsOvhFetcher(BaseFetcher):
    def __init__(self):
        self.client = None
    
    async def _get_client(self):
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=10.0)
        return self.client
    
    async def fetch(self, artist: str, song: str, timestamps: bool = False):
        """Async fetch from Lyrics.ovh API"""
        try:
            logger.info(f"Attempting Lyrics.ovh API for {artist} - {song}")
            
            client = await self._get_client()
            url = f"https://api.lyrics.ovh/v1/{artist}/{song}"
            
            response = await client.get(url)
            
            if response.status_code == 200:
                data = response.json()
                if "lyrics" in data and data["lyrics"].strip():
                    return {
                        "source": "lyrics.ovh",
                        "artist": artist,
                        "title": song,
                        "lyrics": data["lyrics"],
                        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                    }
            
            return None
        
        except Exception as e:
            logger.error(f"Lyrics.ovh error: {e}")
            return None
    
    async def close(self):
        """Close the async client"""
        if self.client:
            await self.client.aclose()