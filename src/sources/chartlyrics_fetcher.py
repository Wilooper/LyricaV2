import httpx
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from src.logger import get_logger
from .base_fetcher import BaseFetcher

logger = get_logger("chartlyrics_fetcher")

class ChartLyricsFetcher(BaseFetcher):
    def __init__(self):
        self.client = None
    
    async def _get_client(self):
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=10.0)
        return self.client
    
    async def fetch(self, artist: str, song: str, timestamps: bool = False):
        """Async fetch from ChartLyrics API"""
        try:
            logger.info(f"Attempting ChartLyrics for {artist} - {song}")
            
            client = await self._get_client()
            url = f"http://api.chartlyrics.com/apiv1.asmx/SearchLyricDirect?artist={artist}&song={song}"
            
            response = await client.get(url)
            
            if response.status_code == 200 and "<Lyric>" in response.text:
                try:
                    root = ET.fromstring(response.content)
                    lyric = root.findtext('.//Lyric')
                    
                    if lyric and lyric.strip():
                        return {
                            "source": "chartlyrics",
                            "artist": artist,
                            "title": song,
                            "lyrics": lyric,
                            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                        }
                except ET.ParseError as e:
                    logger.error(f"XML parsing error: {e}")
                    return None
            
            return None
        
        except Exception as e:
            logger.error(f"ChartLyrics error: {e}")
            return None
    
    async def close(self):
        """Close the async client"""
        if self.client:
            await self.client.aclose()