"""
Async Fetcher Manager - handles lifecycle of fetcher instances
"""
import asyncio
from typing import Dict
from src.logger import get_logger

logger = get_logger("fetcher_manager")

class AsyncFetcherManager:
    """Manages fetcher instances and their lifecycle"""
    
    _instance = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.fetchers: Dict = {}
            cls._instance.initialized = False
        return cls._instance
    
    async def register_fetcher(self, name: str, fetcher_instance):
        """Register a fetcher instance"""
        async with self._lock:
            self.fetchers[name] = fetcher_instance
            logger.info(f"Registered fetcher: {name}")
    
    async def get_fetcher(self, name: str):
        """Get a fetcher instance"""
        if name not in self.fetchers:
            logger.warning(f"Fetcher not found: {name}")
            return None
        return self.fetchers[name]
    
    async def close_all(self):
        """Close all fetcher instances and clean up resources"""
        async with self._lock:
            for name, fetcher in self.fetchers.items():
                try:
                    if hasattr(fetcher, 'close'):
                        await fetcher.close()
                    logger.info(f"Closed fetcher: {name}")
                except Exception as e:
                    logger.error(f"Error closing fetcher {name}: {e}")
            self.fetchers.clear()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close_all()


# Global manager instance
fetcher_manager = AsyncFetcherManager()


async def initialize_fetchers():
    """Initialize all fetchers (call this on app startup)"""
    try:
        from src.sources.genius_fetcher import GeniusFetcher
        from src.sources.lrclib_fetcher import LRCLIBFetcher
        from src.sources.simp_music_fetcher import SimpMusicFetcher
        from src.sources.youtube_fetcher import YoutubeFetcher
        from src.sources.lyricsovh_fetcher import LyricsOvhFetcher
        from src.sources.chartlyrics_fetcher import ChartLyricsFetcher
        from src.sources.lyricsfreek_fetcher import LyricsFreekFetcher
        
        await fetcher_manager.register_fetcher("genius", GeniusFetcher())
        await fetcher_manager.register_fetcher("lrclib", LRCLIBFetcher())
        await fetcher_manager.register_fetcher("simpmusic", SimpMusicFetcher())
        await fetcher_manager.register_fetcher("youtube", YoutubeFetcher())
        await fetcher_manager.register_fetcher("lyricsovh", LyricsOvhFetcher())
        await fetcher_manager.register_fetcher("chartlyrics", ChartLyricsFetcher())
        await fetcher_manager.register_fetcher("lyricsfreek", LyricsFreekFetcher())
        
        logger.info("All fetchers initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Error initializing fetchers: {e}")
        return False


async def cleanup_fetchers():
    """Clean up all fetchers (call this on app shutdown)"""
    await fetcher_manager.close_all()
