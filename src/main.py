from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from datetime import datetime, timezone
import asyncio
import os
import logging

from src.logger import get_logger
from src.cache import clear_cache, cache_stats, make_cache_key, load_from_cache, save_to_cache
from src.config import ADMIN_KEY
from src import __version__
from src.fetch_controller import fetch_lyrics_controller
from src.sentiment_analyzer import analyze_sentiment, analyze_word_frequency, extract_lyrics_text
from src.metadata_extractor import enhance_lyrics_with_metadata, get_metadata_only
from src.sources.jiosaavan_fetcher import search_jiosaavn, get_jiosaavn_stream
from src.trending_analytics import TrendingAnalyticsEngine, Country
from src.sources.fetcher_manager import initialize_fetchers, cleanup_fetchers

# Initialize
logger = get_logger("Lyrica")
app = FastAPI(title="Lyrica", version=__version__)
trending_engine = TrendingAnalyticsEngine(cache_ttl_hours=24)

# Rate limiting
limiter = Limiter(key_func=get_remote_address, default_limits=["15/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda request, exc: JSONResponse(
    status_code=429,
    content={"status": "error", "error": {"message": "Rate limit exceeded. Please wait 35 seconds before retrying."}},
    headers={"Retry-After": "35"}
))

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Admin helper
def verify_admin_key(request: Request) -> bool:
    key = request.query_params.get("key") or request.headers.get("X-ADMIN-KEY")
    return key == ADMIN_KEY


# App lifecycle events
@app.on_event("startup")
async def startup_event():
    """Initialize async resources on app startup"""
    logger.info("Lyrica API starting up...")
    success = await initialize_fetchers()
    if not success:
        logger.warning("Some fetchers failed to initialize")
    logger.info("Lyrica API ready!")


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up async resources on app shutdown"""
    logger.info("Lyrica API shutting down...")
    await cleanup_fetchers()
    logger.info("Lyrica API shutdown complete")


@app.get("/")
@limiter.limit("15/minute")
async def home(request: Request):
    """Main API documentation endpoint"""
    return {
        "api": "Lyrica",
        "version": __version__,
        "status": "active",
        "description": "A comprehensive lyrics API with mood analysis, metadata extraction, and trending insights",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "endpoints": {
            "lyrics": {
                "url": "/lyrics/",
                "method": "GET",
                "description": "Fetch lyrics for a song",
                "examples": [
                    "/lyrics/?artist=The Beatles&song=Imagine",
                    "/lyrics/?artist=The Beatles&song=Imagine&timestamps=true",
                    "/lyrics/?artist=The Beatles&song=Imagine&mood=true",
                    "/lyrics/?artist=The Beatles&song=Imagine&metadata=true",
                    "/lyrics/?artist=The Beatles&song=Imagine&fast=true&timestamps=true&mood=true&metadata=true"
                ]
            },
            "metadata_only": {
                "url": "/metadata/",
                "method": "GET",
                "description": "Get song metadata without lyrics",
                "examples": ["/metadata/?artist=The Beatles&song=Imagine"]
            },
            "trending": {
                "url": "/trending/",
                "method": "GET",
                "description": "Get trending songs by country",
                "examples": [
                    "/trending/?country=US&limit=20",
                    "/trending/?country=IN",
                    "/trending/?countries=US,GB,IN&limit=10"
                ]
            },
            "top_queries": {
                "url": "/analytics/top-queries/",
                "method": "GET",
                "description": "Get top user queries globally or by country",
                "examples": [
                    "/analytics/top-queries/?limit=20",
                    "/analytics/top-queries/?country=US&limit=10",
                    "/analytics/top-queries/?country=US&days=7&limit=15"
                ]
            },
            "trending_by_country": {
                "url": "/analytics/trending-by-country/",
                "method": "GET",
                "description": "Get top queries for each country",
                "examples": ["/analytics/trending-by-country/?limit=10"]
            },
            "trending_vs_queries": {
                "url": "/analytics/trending-vs-queries/",
                "method": "GET",
                "description": "Compare trending songs with top user queries",
                "examples": ["/analytics/trending-vs-queries/?country=US&limit=10"]
            },
            "trending_intersection": {
                "url": "/analytics/trending-intersection/",
                "method": "GET",
                "description": "Find queries that match trending songs",
                "examples": ["/analytics/trending-intersection/?country=US&limit=10"]
            },
            "jiosaavn_search": {
                "url": "/api/jiosaavn/search",
                "method": "GET",
                "description": "Search for songs on JioSaavn",
                "examples": ["/api/jiosaavn/search?q=Imagine"]
            },
            "jiosaavn_play": {
                "url": "/api/jiosaavn/play",
                "method": "GET",
                "description": "Get playable stream URL from JioSaavn",
                "examples": ["/api/jiosaavn/play?songLink=<song_link>"]
            },
            "cache_stats": {
                "url": "/cache/stats",
                "method": "GET",
                "description": "Get cache statistics"
            },
            "music_app": {
                "url": "/app",
                "method": "GET",
                "description": "Access the web-based music application"
            }
        },
        "parameters": {
            "artist": {"type": "string", "required": True, "description": "Artist name"},
            "song": {"type": "string", "required": True, "description": "Song title"},
            "country": {"type": "string", "required": False, "description": "Country code (US, GB, IN, BR, JP, DE, FR, CA, AU, MX)"},
            "countries": {"type": "string", "required": False, "description": "Comma-separated country codes"},
            "limit": {"type": "integer", "required": False, "default": 20, "description": "Number of results"},
            "days": {"type": "integer", "required": False, "description": "Time window in days"},
            "timestamps": {"type": "boolean", "required": False, "default": False, "description": "Include synchronized timestamps"},
            "mood": {"type": "boolean", "required": False, "default": False, "description": "Analyze sentiment and top words"},
            "metadata": {"type": "boolean", "required": False, "default": False, "description": "Include song metadata"},
            "fast": {"type": "boolean", "required": False, "default": False, "description": "Use parallel fetching"}
        },
        "fetchers": {
            "1": "Genius",
            "2": "LRCLIB",
            "3": "SimpMusic",
            "4": "YouTube Music",
            "5": "Lyrics.ovh",
            "6": "ChartLyrics"
        }
    }


@app.get("/lyrics/")
@limiter.limit("15/minute")
async def lyrics(
    request: Request,
    artist: str = None,
    song: str = None,
    country: str = "US",
    timestamps: bool = False,
    timestamp: bool = False,
    pass_param: bool = False,
    sequence: str = None,
    fast: bool = False,
    mood: bool = False,
    metadata: bool = False,
):
    """Fetch lyrics with optional mood analysis and metadata"""
    artist = (artist or "").strip()
    song = (song or "").strip()
    country = country.strip().upper()
    timestamps = timestamps or timestamp
    
    if not artist or not song:
        raise HTTPException(
            status_code=400,
            detail={
                "status": "error",
                "error": {"message": "Artist and song name are required", "timestamp": datetime.now(timezone.utc).isoformat()}
            }
        )

    if pass_param and not sequence:
        raise HTTPException(
            status_code=400,
            detail={
                "status": "error",
                "error": {"message": "Sequence parameter is required when pass=true", "timestamp": datetime.now(timezone.utc).isoformat()}
            }
        )

    logger.info(f"Lyrics request: {artist} - {song} (fast={fast}, mood={mood}, metadata={metadata})")

    try:
        trending_engine.record_user_query(
            user_id=request.client.host,
            query=f"{artist} - {song}",
            country=country
        )
    except Exception as e:
        logger.warning(f"Failed to record user query: {str(e)}")

    # Check cache
    cache_key = make_cache_key(artist, song, timestamps, sequence, fast, mood, metadata)
    cached = load_from_cache(cache_key)
    if cached:
        logger.info(f"Cache hit for {artist} - {song}")
        return cached

    # Fetch lyrics
    try:
        result = await asyncio.wait_for(
            fetch_lyrics_controller(
                artist, song,
                timestamps=timestamps,
                pass_param=pass_param,
                sequence=sequence,
                fast_mode=fast,
            ),
            timeout=60
        )
    except asyncio.TimeoutError:
        logger.error(f"Timeout fetching lyrics for {artist} - {song}")
        raise HTTPException(
            status_code=504,
            detail={
                "status": "error",
                "error": {"message": "Request timed out", "details": "Lyrics fetch took too long", "timestamp": datetime.now(timezone.utc).isoformat()}
            }
        )
    except Exception as e:
        logger.error(f"Error fetching lyrics: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "error": {"message": "Failed to fetch lyrics", "details": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}
            }
        )

    if not isinstance(result, dict):
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "error": {"message": "Invalid response from lyrics fetcher", "timestamp": datetime.now(timezone.utc).isoformat()}
            }
        )

    # Mood analysis
    if mood and result.get("status") == "success":
        data = result.get("data", {})
        lyrics_text = extract_lyrics_text(data)
        if lyrics_text:
            try:
                sentiment = analyze_sentiment(lyrics_text)
                word_freq = analyze_word_frequency(lyrics_text, top_n=5)
                result["mood_analysis"] = {"sentiment": sentiment, "top_words": word_freq}
                logger.info(f"Mood analysis completed for {artist} - {song}")
            except Exception as e:
                logger.warning(f"Mood analysis failed: {str(e)}")
                result["mood_analysis"] = {"error": "Unable to perform mood analysis", "details": str(e)}

    # Metadata
    if metadata and result.get("status") == "success":
        try:
            metadata_result = enhance_lyrics_with_metadata(result, artist, song)
            if asyncio.iscoroutine(metadata_result):
                metadata_result = await asyncio.wait_for(metadata_result, timeout=30)
            result = metadata_result
            logger.info(f"Metadata enhanced for {artist} - {song}")
        except Exception as e:
            logger.warning(f"Metadata enhancement failed: {str(e)}")
            result["metadata_error"] = f"Could not retrieve metadata: {str(e)}"

    # Cache
    if result.get("status") == "success":
        data = result.get("data", {})
        if data.get("lyrics") or data.get("plain_lyrics") or data.get("lyrics_text"):
            try:
                save_to_cache(cache_key, result)
                logger.info(f"Result cached for {artist} - {song}")
            except Exception as e:
                logger.warning(f"Cache save failed: {str(e)}")

    return result


@app.get("/metadata/")
@limiter.limit("15/minute")
async def metadata_endpoint(request: Request, artist: str = None, song: str = None):
    """Get song metadata only (without lyrics)"""
    artist = (artist or "").strip()
    song = (song or "").strip()

    if not artist or not song:
        raise HTTPException(
            status_code=400,
            detail={
                "status": "error",
                "error": {"message": "Artist and song name are required", "timestamp": datetime.now(timezone.utc).isoformat()}
            }
        )

    logger.info(f"Metadata request for {artist} - {song}")

    try:
        result = get_metadata_only(artist, song)
        if asyncio.iscoroutine(result):
            result = await asyncio.wait_for(result, timeout=30)
        return result
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail={
                "status": "error",
                "error": {"message": "Request timed out", "details": "Metadata fetch took too long", "timestamp": datetime.now(timezone.utc).isoformat()}
            }
        )
    except Exception as e:
        logger.error(f"Metadata fetch error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "error": {"message": "Failed to fetch metadata", "details": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}
            }
        )


@app.get("/trending/")
@limiter.limit("15/minute")
async def trending(request: Request, country: str = "US", countries: str = "", limit: int = 20):
    """Get trending songs by country"""
    country = country.strip().upper()
    limit = max(1, min(limit, 100))

    logger.info(f"Trending request: country={country}, limit={limit}")

    try:
        if country and not countries:
            try:
                country_enum = Country[country]
                trending_songs = trending_engine.fetch_trending_songs(country_enum, limit)
                return {
                    "status": "success",
                    "data": {
                        "country": country,
                        "trending": [song.to_dict() for song in trending_songs],
                        "total": len(trending_songs),
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                }
            except KeyError:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "status": "error",
                        "error": {"message": f"Invalid country code: {country}", "valid_countries": [c.value for c in Country], "timestamp": datetime.now(timezone.utc).isoformat()}
                    }
                )

        elif countries:
            country_list = [c.strip().upper() for c in countries.split(",")]
            trending_data = {}
            for c in country_list:
                try:
                    country_enum = Country[c]
                    trending_songs = trending_engine.fetch_trending_songs(country_enum, limit)
                    trending_data[c] = [song.to_dict() for song in trending_songs]
                except KeyError:
                    logger.warning(f"Invalid country code: {c}")
                    continue

            return {
                "status": "success",
                "data": {"countries": trending_data, "timestamp": datetime.now(timezone.utc).isoformat()}
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Trending fetch error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "error": {"message": "Failed to fetch trending data", "details": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}
            }
        )


@app.get("/analytics/top-queries/")
@limiter.limit("15/minute")
async def top_queries(request: Request, limit: int = 20, country: str = "", days: int = None):
    """Get top user queries globally or by country"""
    limit = max(1, min(limit, 100))
    country = country.strip().upper() if country else None

    logger.info(f"Top queries request: limit={limit}, country={country}, days={days}")

    try:
        top_q = trending_engine.get_top_queries(limit=limit, country=country, days=days)
        return {
            "status": "success",
            "data": {
                "scope": "global" if not country else f"country_{country}",
                "time_window": f"{days} days" if days else "all_time",
                "top_queries": [{"query": q, "count": c} for q, c in top_q],
                "total_unique": len(top_q),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        }
    except Exception as e:
        logger.error(f"Top queries fetch error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "error": {"message": "Failed to fetch top queries", "details": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}
            }
        )


@app.get("/analytics/trending-by-country/")
@limiter.limit("15/minute")
async def trending_by_country(request: Request, limit: int = 10):
    """Get top queries for each country"""
    limit = max(1, min(limit, 100))
    logger.info(f"Trending by country request: limit={limit}")

    try:
        top_by_country = trending_engine.get_top_queries_by_country(limit=limit)
        return {
            "status": "success",
            "data": {
                "countries": {
                    country: [{"query": q, "count": c} for q, c in queries]
                    for country, queries in top_by_country.items()
                },
                "total_countries": len(top_by_country),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        }
    except Exception as e:
        logger.error(f"Trending by country error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "error": {"message": "Failed to fetch trending by country", "details": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}
            }
        )


@app.get("/analytics/trending-vs-queries/")
@limiter.limit("15/minute")
async def trending_vs_queries(request: Request, country: str = "US", limit: int = 10):
    """Compare trending songs with top user queries"""
    country = country.strip().upper()
    limit = max(1, min(limit, 100))
    logger.info(f"Trending vs queries request: country={country}, limit={limit}")

    try:
        country_enum = Country[country]
        comparison = trending_engine.get_trending_vs_user_queries(country_enum, limit)
        return {"status": "success", "data": comparison}
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail={
                "status": "error",
                "error": {"message": f"Invalid country code: {country}", "valid_countries": [c.value for c in Country], "timestamp": datetime.now(timezone.utc).isoformat()}
            }
        )
    except Exception as e:
        logger.error(f"Trending vs queries error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "error": {"message": "Failed to fetch trending vs queries", "details": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}
            }
        )


@app.get("/analytics/trending-intersection/")
@limiter.limit("15/minute")
async def trending_intersection(request: Request, country: str = "US", limit: int = 10):
    """Find queries that match trending songs"""
    country = country.strip().upper()
    limit = max(1, min(limit, 100))
    logger.info(f"Trending intersection request: country={country}, limit={limit}")

    try:
        country_enum = Country[country]
        matches = trending_engine.get_trending_intersection(country_enum, limit)
        return {
            "status": "success",
            "data": {
                "country": country,
                "matches": matches,
                "total_matches": len(matches),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        }
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail={
                "status": "error",
                "error": {"message": f"Invalid country code: {country}", "valid_countries": [c.value for c in Country], "timestamp": datetime.now(timezone.utc).isoformat()}
            }
        )
    except Exception as e:
        logger.error(f"Trending intersection error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "error": {"message": "Failed to fetch trending intersection", "details": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}
            }
        )


@app.get("/api/jiosaavn/search")
@limiter.limit("15/minute")
async def jiosaavn_search_endpoint(request: Request, q: str = None):
    """Search for songs on JioSaavn"""
    q = (q or "").strip()
    
    if not q:
        raise HTTPException(
            status_code=400,
            detail={
                "status": "error",
                "error": {"message": "Query parameter 'q' is required", "timestamp": datetime.now(timezone.utc).isoformat()}
            }
        )

    logger.info(f"JioSaavn search query: {q}")

    try:
        results = search_jiosaavn(q)
        if asyncio.iscoroutine(results):
            results = await asyncio.wait_for(results, timeout=30)
        return {"status": "success", "results": results}
    except asyncio.TimeoutError:
        logger.error(f"Timeout searching JioSaavn for: {q}")
        raise HTTPException(
            status_code=504,
            detail={
                "status": "error",
                "error": {"message": "Request timed out", "details": "JioSaavn search took too long", "timestamp": datetime.now(timezone.utc).isoformat()}
            }
        )
    except Exception as e:
        logger.error(f"JioSaavn search error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "error": {"message": "Failed to search JioSaavn", "details": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}
            }
        )


@app.get("/api/jiosaavn/play")
@limiter.limit("15/minute")
async def jiosaavn_play_endpoint(request: Request, songLink: str = None):
    """Get playable stream URL from JioSaavn"""
    song_link = (songLink or "").strip()
    
    if not song_link:
        raise HTTPException(
            status_code=400,
            detail={
                "status": "error",
                "error": {"message": "songLink parameter is required", "timestamp": datetime.now(timezone.utc).isoformat()}
            }
        )

    logger.info(f"JioSaavn play request for: {song_link}")

    try:
        data = get_jiosaavn_stream(song_link)
        if asyncio.iscoroutine(data):
            data = await asyncio.wait_for(data, timeout=30)
        
        if not data or not isinstance(data, dict):
            raise HTTPException(
                status_code=500,
                detail={
                    "status": "error",
                    "error": {"message": "Invalid response from JioSaavn", "timestamp": datetime.now(timezone.utc).isoformat()}
                }
            )

        if not data.get("stream_url"):
            raise HTTPException(
                status_code=500,
                detail={
                    "status": "error",
                    "error": {"message": "Unable to fetch stream URL", "timestamp": datetime.now(timezone.utc).isoformat()}
                }
            )

        return {"status": "success", "data": data}
    except asyncio.TimeoutError:
        logger.error(f"Timeout fetching stream for: {song_link}")
        raise HTTPException(
            status_code=504,
            detail={
                "status": "error",
                "error": {"message": "Request timed out", "details": "Stream fetch took too long", "timestamp": datetime.now(timezone.utc).isoformat()}
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"JioSaavn play error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "error": {"message": "Failed to fetch stream", "details": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}
            }
        )


@app.get("/app")
async def app_page():
    """Serve the web-based music application"""
    try:
        return FileResponse("templates/index.html")
    except Exception as e:
        logger.error(f"Failed to render app page: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "error": {"message": "Failed to load application", "timestamp": datetime.now(timezone.utc).isoformat()}
            }
        )


@app.get("/cache/stats")
@limiter.limit("15/minute")
async def route_cache_stats(request: Request):
    """Get cache statistics and information"""
    try:
        stats = cache_stats()
        return {"status": "success", **stats}
    except Exception as e:
        logger.error(f"Cache stats error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "error": {"message": "Failed to retrieve cache stats", "details": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}
            }
        )


@app.post("/admin/cache/clear")
async def admin_clear_cache(request: Request):
    """Clear all cached data (Admin only)"""
    if not verify_admin_key(request):
        raise HTTPException(status_code=403, detail={"error": "unauthorized"})
    
    try:
        result = clear_cache()
        logger.info("Cache cleared")
        return {"status": "cache cleared", "details": result}
    except Exception as e:
        logger.error(f"Cache clear error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "error": {"message": "Failed to clear cache", "details": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}
            }
        )


@app.get("/admin/cache/stats")
async def admin_cache_stats(request: Request):
    """Get cache statistics (Admin only)"""
    if not verify_admin_key(request):
        raise HTTPException(status_code=403, detail={"error": "unauthorized"})
    
    return cache_stats()


@app.get("/favicon.ico")
async def favicon():
    """Favicon endpoint"""
    return "", 204


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """Handle 404 errors"""
    return JSONResponse(
        status_code=404,
        content={
            "status": "error",
            "error": {"message": "Endpoint not found", "timestamp": datetime.now(timezone.utc).isoformat()}
        }
    )


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    """Handle 500 errors"""
    logger.error(f"Internal server error: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "error": {"message": "Internal server error", "timestamp": datetime.now(timezone.utc).isoformat()}
        }
    )



