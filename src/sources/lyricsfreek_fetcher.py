import re
import httpx
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from src.logger import get_logger
from .base_fetcher import BaseFetcher

logger = get_logger("lyricsfreek_fetcher")

class LyricsFreekFetcher(BaseFetcher):
    def __init__(self):
        self.client = None
    
    async def _get_client(self):
        if self.client is None:
            self.client = httpx.AsyncClient(
                timeout=10.0,
                headers={"User-Agent": "Mozilla/5.0 (compatible; LyricsFetcher/1.0)"}
            )
        return self.client
    
    async def fetch(self, artist: str, song: str, timestamps: bool = False):
        """Async fetch from LyricsFreek"""
        try:
            logger.info(f"Attempting LyricsFreek for {artist} - {song}")
            
            search_artist = artist.lower().replace(" ", "-")
            search_title = song.lower().replace(" ", "-")
            url = f"https://www.lyricsfreek.com/{search_artist}/{search_title}-lyrics"
            
            client = await self._get_client()
            response = await client.get(url, follow_redirects=True)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                lyrics_div = soup.find("div", {"class": "lyrics"})
                
                if lyrics_div:
                    lyrics = lyrics_div.get_text(separator="\n").strip()
                    # Remove submission section
                    lyrics = re.sub(
                        r"\n*Submit Corrections.*",
                        "",
                        lyrics,
                        flags=re.IGNORECASE | re.DOTALL
                    ).strip()
                    
                    if lyrics:
                        return {
                            "source": "lyricsfreek",
                            "artist": artist,
                            "title": song,
                            "lyrics": lyrics,
                            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                        }
            
            return None
        
        except Exception as e:
            logger.error(f"LyricsFreek error: {e}")
            return None
    
    async def close(self):
        """Close the async client"""
        if self.client:
            await self.client.aclose()