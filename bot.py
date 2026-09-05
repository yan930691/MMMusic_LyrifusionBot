from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
import os
import logging
import asyncio
from dotenv import load_dotenv

# ============ Render: Create cookies.txt from Environment Variable ============
cookies_content = os.getenv("COOKIES_CONTENT")
if cookies_content:
    try:
        with open("cookies.txt", "w") as f:
            f.write(cookies_content)
        logging.info("✅ cookies.txt created from COOKIES_CONTENT")
    except Exception as e:
        logging.error(f"❌ Failed to create cookies.txt: {e}")
else:
    logging.warning("⚠️ COOKIES_CONTENT not found in environment variables")

# ============ Load environment variables ============
load_dotenv()
import requests
from pytubefix import Search, YouTube
import yt_dlp
from aiogram import Bot, Dispatcher, types
from bs4 import BeautifulSoup
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, USLT, Encoding
from PIL import Image, UnidentifiedImageError
from io import BytesIO
from ddgs import DDGS
import re
import uuid
import glob
import shutil
import json

# Force INFO level logs globally so we can see what's happening
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    force=True
)

# Monkey-patch Python 3.9's logging to accept 'once' kwarg (added in Python 3.12)
for _method_name in ('debug', 'info', 'warning', 'error', 'critical'):
    _original = getattr(logging.Logger, _method_name)
    def _make_patched(orig):
        def _patched(self, msg, *args, **kwargs):
            kwargs.pop('once', None)
            return orig(self, msg, *args, **kwargs)
        return _patched
    setattr(logging.Logger, _method_name, _make_patched(_original))

class YTDLLogger:
    """Custom logger to bypass yt-dlp's Python 3.9 'once=True' bug"""
    def debug(self, msg, *args, **kwargs):
        pass
    def warning(self, msg, *args, **kwargs):
        logging.info(f"yt-dlp warn: {msg}")
    def error(self, msg, *args, **kwargs):
        logging.error(f"yt-dlp error: {msg}")
import time
from urllib.parse import quote_plus
import sys

# Auto-install Node.js on Render so yt-dlp can decipher YouTube signatures
NODE_DIR = "node_bin"
_NODE_VERSION = "v22.14.0"
_NODE_URL = f"https://nodejs.org/dist/{_NODE_VERSION}/node-{_NODE_VERSION}-linux-x64.tar.xz"
if sys.platform != 'win32':
    import subprocess
    _need_install = not os.path.exists(NODE_DIR)
    if os.path.exists(NODE_DIR):
        _ver = subprocess.run([f"{NODE_DIR}/bin/node", "--version"], capture_output=True, text=True)
        if _ver.returncode == 0 and not _ver.stdout.strip().startswith("v22"):
            import shutil
            shutil.rmtree(NODE_DIR, ignore_errors=True)
            _need_install = True
    if _need_install:
        logging.warning(f"Downloading Node.js {_NODE_VERSION}...")
        os.makedirs(NODE_DIR, exist_ok=True)
        subprocess.run(["wget", "-qO", "node.tar.xz", _NODE_URL])
        subprocess.run(["tar", "xf", "node.tar.xz", "-C", NODE_DIR, "--strip-components=1"])
        if os.path.exists("node.tar.xz"):
            os.remove("node.tar.xz")
        logging.warning("Node.js installed.")

NODE_BIN = None
if sys.platform != 'win32':
    os.environ["PATH"] = f"{os.path.abspath(NODE_DIR)}/bin:" + os.environ.get("PATH", "")
    NODE_BIN = f"{os.path.abspath(NODE_DIR)}/bin/node"

# Auto-setup PO Token server for YouTube Proof-of-Origin bypass
BGUTIL_DIR = "bgutil-ytdlp-pot-provider"
_pot_server_process = None
_pot_status = "skipped (windows)"
if sys.platform != 'win32':
    import subprocess as _sp
    _node_path = os.path.abspath(NODE_DIR) + "/bin"
    _env = os.environ.copy()
    _env["PATH"] = f"{_node_path}:" + _env.get("PATH", "")

    if not os.path.exists(f"{BGUTIL_DIR}/server/build/main.js") or not os.path.exists(f"{BGUTIL_DIR}/.node_version") or open(f"{BGUTIL_DIR}/.node_version").read().strip() != _NODE_VERSION:
        try:
            logging.warning("=== PO TOKEN SERVER SETUP STARTING ===")
            import shutil as _shutil
            if os.path.exists(BGUTIL_DIR):
                _shutil.rmtree(BGUTIL_DIR, ignore_errors=True)

            r = _sp.run(["git", "clone", "--single-branch", "--branch", "1.3.1",
                          "https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git", BGUTIL_DIR],
                         capture_output=True, text=True, env=_env)
            logging.warning(f"PO Token: git clone rc={r.returncode}")

            _build_env = _env.copy()
            _build_env["NODE_ENV"] = "development"

            r = _sp.run([f"{_node_path}/npm", "ci", "--include=dev"], cwd=f"{BGUTIL_DIR}/server",
                       capture_output=True, text=True, env=_build_env)
            logging.warning(f"PO Token: npm ci rc={r.returncode}")

            r = _sp.run([f"{_node_path}/npm", "install", "typescript"], cwd=f"{BGUTIL_DIR}/server",
                       capture_output=True, text=True, env=_build_env)
            logging.warning(f"PO Token: npm install typescript rc={r.returncode}")

            r = _sp.run([f"{_node_path}/npx", "--yes", "tsc"], cwd=f"{BGUTIL_DIR}/server",
                       capture_output=True, text=True, env=_build_env)
            logging.warning(f"PO Token: tsc compile rc={r.returncode}")

            if os.path.exists(f"{BGUTIL_DIR}/server/build/main.js"):
                logging.warning("=== PO TOKEN SERVER BUILT OK ===")
                with open(f"{BGUTIL_DIR}/.node_version", "w") as _vf:
                    _vf.write(_NODE_VERSION)
                _pot_status = "built"
            else:
                logging.error("PO Token: build/main.js NOT FOUND after tsc!")
                _pot_status = "build failed"
        except Exception as _build_err:
            logging.error(f"PO Token build exception: {_build_err}")
            _pot_status = f"exception: {_build_err}"
    else:
        logging.warning("PO Token: build/main.js already exists, skipping build")
        _pot_status = "already built"

    # Start the PO Token HTTP server as a background process
    if os.path.exists(f"{BGUTIL_DIR}/server/build/main.js"):
        try:
            _pot_log_path = f"{BGUTIL_DIR}/server/pot_server.log"
            _pot_log = open(_pot_log_path, "w")
            _pot_server_process = _sp.Popen(
                [f"{_node_path}/node", "--experimental-require-module", "build/main.js"],
                cwd=f"{BGUTIL_DIR}/server",
                env=_env,
                stdout=_pot_log, stderr=_pot_log
            )
            import time as _time
            for _attempt in range(15):
                _time.sleep(2)
                if _pot_server_process.poll() is not None:
                    _pot_server_process = None
                    _pot_status = "server crashed"
                    break
                try:
                    _ping = requests.get("http://127.0.0.1:4416/ping", timeout=3)
                    logging.warning(f"=== PO TOKEN SERVER ALIVE (PID:{_pot_server_process.pid}) ping={_ping.status_code} (attempt {_attempt+1}) ===")
                    _pot_status = "RUNNING"
                    break
                except Exception:
                    pass
        except Exception as e:
            logging.error(f"PO Token server start failed: {e}")
            _pot_status = f"start failed: {e}"

logging.warning(f"=== PO TOKEN STATUS: {_pot_status} ===")

BS4_AVAILABLE = True

# Import Rust-dependent DuckDuckGo search
try:
    from ddgs import DDGS
    RUST_SEARCH_AVAILABLE = True
except ImportError:
    RUST_SEARCH_AVAILABLE = False
    logging.warning("DuckDuckGo search not available. Install with: pip install duckduckgo-search")

# Import Groq for AI
try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False
    logging.warning("Groq not available. Install with: pip install groq")

# ================== LOGGING CONFIGURATION ================== #
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)

# ================== CONFIGURATION SETUP ================== #
class Config:
    def __init__(self):
        self.TOKEN = self.get_token()
        self.GROQ_API_KEY = self.get_groq_key()
        self.COOKIES_FILE = self.get_cookies_file()
        self.ITUNES_API = "https://itunes.apple.com/search"
        self.DEEZER_API = "https://api.deezer.com/search"

    def get_token(self):
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        if token:
            return token
        try:
            with open('token.txt', 'r') as f:
                return f.read().strip()
        except FileNotFoundError:
            logging.error("Missing bot token. Set TELEGRAM_BOT_TOKEN in .env or create token.txt")
            return None

    def get_groq_key(self):
        key = os.getenv('GROQ_API_KEY')
        if key:
            return key
        try:
            with open('groq_key.txt', 'r') as f:
                return f.read().strip()
        except FileNotFoundError:
            return None

    def get_cookies_file(self):
        path = os.getenv('COOKIES_FILE', 'cookies.txt')
        if os.path.exists(path):
            return path
        return None

from aiogram.client.session.aiohttp import AiohttpSession

config = Config()
if not config.TOKEN:
    exit("Bot token not found. Please create token.txt with your Telegram bot token.")

# Initialize bot with extended timeout for slow Render uploads
session = AiohttpSession(timeout=300.0)
bot = Bot(token=config.TOKEN, session=session)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Initialize Groq client if available
groq_client = None
if config.GROQ_API_KEY and GROQ_AVAILABLE:
    try:
        groq_client = Groq(api_key=config.GROQ_API_KEY)
        logging.info("Groq AI client initialized")
    except Exception as e:
        logging.error(f"Groq client error: {e}")

# ================== BOT STATES ================== #
class MusicStates(StatesGroup):
    waiting_song = State()
    confirm_cover = State()
    waiting_lyrics = State()

# ================== ADVANCED WEB SEARCH WITH RUST ================== #
class AdvancedWebSearch:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        self.ddgs = None
        if RUST_SEARCH_AVAILABLE:
            try:
                self.ddgs = DDGS()
                logging.info("DuckDuckGo search initialized (Rust-powered)")
            except Exception as e:
                logging.error(f"DuckDuckGo initialization error: {e}")

    async def search_web(self, query):
        results = []
        if self.ddgs:
            results.extend(await self.search_duckduckgo(query))
        results.extend(await self.search_wikipedia(query))
        results.extend(await self.search_youtube_info(query))
        seen = set()
        unique_results = []
        for result in results:
            key = result.get('title', '') + result.get('url', '')
            if key not in seen:
                unique_results.append(result)
                seen.add(key)
        return unique_results[:15]

    async def search_duckduckgo(self, query):
        try:
            search_queries = [
                f'"{query}" song details artist album',
                f'{query} movie soundtrack Bollywood',
                f'{query} singer composer music',
                query
            ]
            results = []
            for search_query in search_queries[:2]:
                try:
                    ddg_results = list(self.ddgs.text(search_query, max_results=5))
                    for result in ddg_results:
                        results.append({
                            'title': result.get('title', ''),
                            'snippet': result.get('body', ''),
                            'url': result.get('href', ''),
                            'source': 'DuckDuckGo'
                        })
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logging.error(f"DuckDuckGo search error for '{search_query}': {e}")
                    continue
            return results[:8]
        except Exception as e:
            logging.error(f"DuckDuckGo search error: {e}")
            return []

    async def search_wikipedia(self, query):
        try:
            search_terms = [query, f"{query} song", f"{query} bollywood", f"{query} movie"]
            results = []
            for term in search_terms:
                try:
                    api_url = "https://en.wikipedia.org/w/api.php"
                    params = {
                        'action': 'query',
                        'list': 'search',
                        'srsearch': term,
                        'format': 'json',
                        'srlimit': 3
                    }
                    response = self.session.get(api_url, params=params, timeout=8)
                    if response.status_code == 200:
                        data = response.json()
                        for page in data.get('query', {}).get('search', []):
                            try:
                                summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote_plus(page['title'])}"
                                summary_response = self.session.get(summary_url, timeout=5)
                                if summary_response.status_code == 200:
                                    summary_data = summary_response.json()
                                    results.append({
                                        'title': summary_data.get('title', ''),
                                        'snippet': summary_data.get('extract', ''),
                                        'url': summary_data.get('content_urls', {}).get('desktop', {}).get('page', '')
                                    })
                            except:
                                continue
                    if results:
                        break
                except Exception as e:
                    continue
            return results[:5]
        except Exception as e:
            logging.error(f"Wikipedia search error: {e}")
            return []

    async def search_youtube_info(self, query):
        try:
            s = Search(query)
            results = []
            if s.videos:
                for video in s.videos[:5]:
                    results.append({
                        'title': video.title,
                        'snippet': f"YouTube: {video.title} - {video.author}...",
                        'url': video.watch_url
                    })
            return results
        except Exception as e:
            logging.warning(f"YouTube search skipped (non-critical): {e}")
            return []

    async def search_jiosaavn_web(self, query):
        try:
            jiosaavn_query = f"site:jiosaavn.com {query}"
            results = []
            if self.ddgs:
                try:
                    ddg_results = list(self.ddgs.text(jiosaavn_query, max_results=3))
                    for result in ddg_results:
                        if 'jiosaavn.com' in result.get('href', ''):
                            results.append({
                                'title': result.get('title', ''),
                                'snippet': result.get('body', ''),
                                'url': result.get('href', ''),
                                'source': 'JioSaavn'
                            })
                except Exception as e:
                    logging.error(f"JioSaavn search error: {e}")
            return results[:3]
        except Exception as e:
            logging.error(f"JioSaavn web search error: {e}")
            return []

    async def scrape_jiosaavn_page(self, url):
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
            }
            response = self.session.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                for script in soup(["script", "style"]):
                    script.decompose()
                text_content = soup.get_text()
                lines = (line.strip() for line in text_content.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                text = ' '.join(chunk for chunk in chunks if chunk)
                return text[:4000]
        except Exception as e:
            logging.error(f"JioSaavn scraping error: {e}")
            return None

# ================== AI METADATA FETCHER ================== #
class AIMetadataFetcher:
    def __init__(self, groq_client, web_search):
        self.groq_client = groq_client
        self.web_search = web_search
        self.known_songs = {
            'humne ghar chhoda hai dil movie': {
                'title': 'Humne Ghar Chhoda Hai',
                'artist': 'Udit Narayan, Anuradha Paudwal',
                'album': 'Dil (1990)',
                'confidence': 0.95
            },
            'humne ghar chhoda hai': {
                'title': 'Humne Ghar Chhoda Hai',
                'artist': 'Udit Narayan, Anuradha Paudwal',
                'album': 'Dil (1990)',
                'confidence': 0.9
            },
            'tujhe dekha to ye jana sanam ddlj': {
                'title': 'Tujhe Dekha To Ye Jana Sanam',
                'artist': 'Lata Mangeshkar, Kumar Sanu',
                'album': 'Dilwale Dulhania Le Jayenge (1995)',
                'confidence': 0.95
            },
            'kal ho naa ho': {
                'title': 'Kal Ho Naa Ho',
                'artist': 'Sonu Nigam',
                'album': 'Kal Ho Naa Ho (2003)',
                'confidence': 0.9
            },
            'mere sapno ki rani ddlj': {
                'title': 'Mere Sapno Ki Rani',
                'artist': 'Lata Mangeshkar, Mukesh',
                'album': 'Aradhana (1969)',
                'confidence': 0.9
            },
            'kuch kuch hota hai': {
                'title': 'Kuch Kuch Hota Hai',
                'artist': 'Udit Narayan, Alka Yagnik',
                'album': 'Kuch Kuch Hota Hai (1998)',
                'confidence': 0.9
            }
        }

    async def search_with_ai(self, query):
        try:
            query_lower = query.lower().strip()
            if query_lower in self.known_songs:
                logging.info(f"Found in database: {query}")
                return self.known_songs[query_lower]

            jiosaavn_metadata = await self.search_jiosaavn_with_ai(query)
            if jiosaavn_metadata and jiosaavn_metadata.get('confidence', 0) > 0.7:
                logging.info(f"Found via JioSaavn scraping: {jiosaavn_metadata}")
                return jiosaavn_metadata

            search_results = await self.web_search.search_web(query)
            if self.groq_client and search_results:
                ai_metadata = await self.ai_analyze_metadata(query, search_results)
                if ai_metadata and ai_metadata.get('confidence', 0) > 0.5:
                    return ai_metadata

            return await self.enhanced_pattern_matching(query, search_results)

        except Exception as e:
            logging.error(f"AI search error: {e}")
            return self.basic_fallback(query)

    async def ai_analyze_metadata(self, query, search_results):
        try:
            if not search_results:
                return None

            context = "\n".join([
                f"Title: {result.get('title', '')}\nContent: {result.get('snippet', '')}\n---"
                for result in search_results[:6]
            ])

            prompt = f"""Analyze these search results for the song: "{query}"

Search Results:
{context}

Extract accurate metadata. Rules:
1. For Indian/Bollywood songs, provide actual singer names
2. Album should be "Movie Name (Year)" format for movie songs
3. Use complete, accurate song title
4. Be precise based on evidence
5. IMPORTANT: If query mentions a specific movie name (like "Teree Sang"), prioritize results from that movie
6. Don't confuse similar song titles from different movies/albums

Respond with ONLY this JSON:
{{"title": "Song Title", "artist": "Singer Name(s)", "album": "Album/Movie (Year)", "confidence": 0.0-1.0}}"""

            response = self.groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": "Extract music metadata. Respond only with valid JSON. Pay attention to specific movie names mentioned in queries."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=150
            )

            ai_response = response.choices[0].message.content.strip()
            if ai_response.startswith('```'):
                ai_response = re.sub(r'```(json)?', '', ai_response).strip()
            if ai_response.endswith('```'):
                ai_response = ai_response[:-3].strip()

            metadata = json.loads(ai_response)
            if all(key in metadata for key in ['title', 'artist', 'album', 'confidence']):
                logging.info(f"AI metadata: {metadata}")
                return metadata

        except Exception as e:
            logging.error(f"AI analysis error: {e}")
            return None

    async def enhanced_pattern_matching(self, query, search_results):
        context_text = " ".join([
            result.get('title', '') + " " + result.get('snippet', '')
            for result in search_results
        ]).lower()

        patterns = [
            (r'(.+?)\s+from\s+(.+?)\s+movie', lambda m: (m.group(1).strip(), m.group(2).strip())),
            (r'(.+?)\s+(.+?)\s+movie', lambda m: (m.group(1).strip(), m.group(2).strip())),
            (r'(.+?)\s+dil\s+movie', lambda m: (m.group(1).strip(), 'Dil')),
        ]

        for pattern, extractor in patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                song_name, movie_name = extractor(match)
                artist = self.extract_artist_from_context(context_text, song_name)
                year = self.extract_year_from_context(context_text, movie_name)
                album = movie_name.title()
                if year:
                    album = f"{album} ({year})"
                return {
                    'title': song_name.title(),
                    'artist': artist or 'Various Artists',
                    'album': album,
                    'confidence': 0.7
                }

        return self.basic_fallback(query)

    def extract_artist_from_context(self, context, song_name):
        patterns = [
            rf'{re.escape(song_name.lower())}.*?sung by ([^.,\n]+)',
            rf'{re.escape(song_name.lower())}.*?singer[s]?\s*:?\s*([^.,\n]+)',
            rf'performed by ([^.,\n]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, context, re.IGNORECASE)
            if match:
                return re.sub(r'\s*(and|&)\s*', ', ', match.group(1).strip())
        return None

    def extract_year_from_context(self, context, movie_name):
        if not movie_name:
            return None
        patterns = [
            rf'{re.escape(movie_name.lower())}.*?(19\d{{2}}|20\d{{2}})',
            rf'(19\d{{2}}|20\d{{2}}).*?{re.escape(movie_name.lower())}',
        ]
        for pattern in patterns:
            match = re.search(pattern, context, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    def basic_fallback(self, query):
        return {
            'title': query.title(),
            'artist': 'Various Artists',
            'album': 'Unknown Album',
            'confidence': 0.3
        }

    async def search_jiosaavn_with_ai(self, query):
        try:
            jiosaavn_results = await self.web_search.search_jiosaavn_web(query)
            if not jiosaavn_results:
                return None
            best_result = jiosaavn_results[0]
            page_content = await self.web_search.scrape_jiosaavn_page(best_result['url'])
            if not page_content:
                return None
            return await self.ai_extract_jiosaavn_metadata(query, page_content, best_result)
        except Exception as e:
            logging.error(f"JioSaavn AI search error: {e}")
            return None

    async def ai_extract_jiosaavn_metadata(self, query, page_content, result_info):
        try:
            prompt = f"""Extract song metadata from this JioSaavn page content for the query: "{query}"

Page Content:
{page_content}

Search Result Title: {result_info.get('title', '')}

Instructions:
1. Find the exact song title, artist name(s), and album name
2. For Bollywood songs, include movie name in album as "Movie Name (Year)"  
3. Extract all featured artists and singers
4. Be precise and accurate based on the page content
5. If multiple songs are found, pick the one most relevant to the query
6. Pay special attention to movie names like "Teree Sang" vs other similar songs

Respond with ONLY this JSON:
{{"title": "Exact Song Title", "artist": "Singer Name(s)", "album": "Album/Movie (Year)", "confidence": 0.0-1.0, "source": "JioSaavn"}}"""

            if not self.groq_client:
                return None
            response = self.groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": "Extract music metadata from JioSaavn page content. Respond only with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=200
            )

            ai_response = response.choices[0].message.content.strip()
            if ai_response.startswith('```'):
                ai_response = re.sub(r'```(json)?', '', ai_response).strip()
            if ai_response.endswith('```'):
                ai_response = ai_response[:-3].strip()

            metadata = json.loads(ai_response)
            if all(key in metadata for key in ['title', 'artist', 'album', 'confidence']):
                logging.info(f"JioSaavn AI metadata: {metadata}")
                return metadata
        except Exception as e:
            logging.error(f"JioSaavn AI extraction error: {e}")
            return None

# Initialize components
web_search = AdvancedWebSearch()
ai_fetcher = AIMetadataFetcher(groq_client, web_search)

# ================== METADATA PARSING ================== #
async def clean_and_parse_metadata(original_query, youtube_title=None, youtube_uploader=None):
    logging.info(f"Parsing metadata for: '{original_query}'")
    try:
        ai_metadata = await ai_fetcher.search_with_ai(original_query)
        if ai_metadata:
            logging.info(f"Metadata result: {ai_metadata}")
            return ai_metadata
        return {
            'title': original_query.title(),
            'artist': 'Various Artists',
            'album': 'Unknown Album',
            'confidence': 0.2
        }
    except Exception as e:
        logging.error(f"Metadata parsing error: {e}")
        return {
            'title': original_query.title(),
            'artist': 'Various Artists',
            'album': 'Unknown Album',
            'confidence': 0.1
        }

# ================== FILE MANAGEMENT ================== #
def setup_directories():
    directories = ['downloads', 'processed', 'covers']
    for directory in directories:
        os.makedirs(directory, exist_ok=True)

async def cleanup_user_files(user_data):
    files_to_clean = ['file_path', 'cover_path']
    for file_key in files_to_clean:
        if file_key in user_data:
            file_path = user_data[file_key]
            if file_path and os.path.exists(file_path):
                try:
                    os.unlink(file_path)
                except Exception as e:
                    logging.error(f"Cleanup error: {e}")

setup_directories()

# ================== COMMAND HANDLERS (မြန်မာလို) ================== #
@dp.message(Command("start"))
async def start_command(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    await cleanup_user_files(user_data)
    await state.clear()
    
    ai_status = "ဖွင့်ထားပြီ" if groq_client else "ပိတ်ထားပါတယ် (Groq API Key ထည့်ပါ)"
    welcome_text = (
        "🎵 **AI Music Assistant မှ ကြိုဆိုပါတယ်!** 🎵\n\n"
        "သီချင်းတွေကို စာသားနဲ့အတူ Samsung Music Player အတွက် ဒေါင်းလုဒ်ရယူနိုင်ပါတယ်။\n\n"
        "✨ **ဘယ်လိုအလုပ်လုပ်လဲ:**\n"
        "1. သီချင်းနာမည်ပို့ပါ (ဥပမာ - 'Humne ghar chhoda hai Dil movie')\n"
        "2. AI က တိကျတဲ့ သီချင်းအချက်အလက်တွေကို ရှာဖွေပေးမယ်\n"
        "3. ကာဗာပုံ အတည်ပြုပါ\n"
        "4. စာသားပို့ပါ\n"
        "5. ပြီးပြည့်စုံတဲ့ MP3 ကို ရရှိမယ်!\n\n"
        " *အခက်အခဲရှိရင် /help ကိုသုံးပါ*\n"
        " *DM : @Ri5h11 ကို အကူအညီအတွက် ဆက်သွယ်ပါ*\n"
        "🚀 **စတင်ရန် သီချင်းနာမည်ပို့ပါ!**"
    )
    
    await message.answer(welcome_text, parse_mode="Markdown")
    await state.set_state(MusicStates.waiting_song)

@dp.message(Command("help"))
async def help_command(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    await cleanup_user_files(user_data)
    await state.clear()
    
    help_text = (
        "🆘 **AI Music Assistant အကူအညီ**\n\n"
        "📋 **အသုံးပြုပုံ:**\n"
        "1. သီချင်းနာမည်ပို့ပါ\n"
        "2. AI က ရှာဖွေပြီး အချက်အလက်တွေကို ထုတ်ယူမယ်\n"
        "3. ကာဗာပုံ အတည်ပြုပါ\n"
        "4. စာသားပို့ပါ\n"
        "5. ပြီးပြည့်စုံတဲ့ MP3 ကို ရရှိမယ်!\n\n"
        "💡 **ဥပမာများ:**\n"
        "- `Humne ghar chhoda hai Dil movie`\n"
        "- `Tujhe dekha to ye jana sanam DDLJ`\n"
        "- `Kal ho naa ho`\n\n"
        "ဆက်သွယ်ရန်: [@Ri5h11](https://t.me/Ri5h11)"
    )
    
    await message.answer(help_text, parse_mode="Markdown", disable_web_page_preview=True)

@dp.message(Command("cancel"))
async def cancel_command(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("ℹ️ လုပ်ဆောင်မှုမရှိပါ။")
        return
    
    user_data = await state.get_data()
    await cleanup_user_files(user_data)
    await state.clear()
    await message.answer("❌ လုပ်ဆောင်မှုကို ပယ်ဖျက်လိုက်ပါပြီ။ ပြန်စရန် /start ကိုသုံးပါ။")

# ================== SONG PROCESSING (မြန်မာလို) ================== #
@dp.message(MusicStates.waiting_song)
async def handle_song_request(message: types.Message, state: FSMContext):
    if message.text and message.text.startswith('/'):
        return

    if not message.text:
        await message.answer("❌ ကျေးဇူးပြု၍ သီချင်းနာမည်ကို စာသားအနေနဲ့ ပို့ပါ။")
        return

    song_query = message.text.strip()
    if len(song_query) < 3:
        await message.answer("❌ ကျေးဇူးပြု၍ အနည်းဆုံး စာလုံး ၃ လုံးထက်ပိုတဲ့ နာမည်ကို ရိုက်ထည့်ပါ။")
        return

    await state.update_data(song_query=song_query, cover_attempts=0)

    search_methods = []
    if groq_client:
        search_methods.append("AI Analysis")
    search_methods.extend(["Web Search", "Database", "Pattern Matching"])
    
    search_msg = await message.answer(f"🔍 '{song_query}' ကို {' + '.join(search_methods)} နည်းလမ်းတွေနဲ့ ရှာဖွေနေပါပြီ...")

    try:
        ai_metadata = await clean_and_parse_metadata(song_query)
        cover_search_query = f"{ai_metadata['title']} {ai_metadata['artist']} {ai_metadata['album']}"
        cover_url, cover_metadata = await search_cover_art(cover_search_query)
        
        if not cover_url:
            cover_url, cover_metadata = await search_cover_art(song_query)

        await bot.delete_message(message.chat.id, search_msg.message_id)
        
        if cover_url:
            cover_path = await download_and_process_cover(cover_url)
            if cover_path:
                confidence = ai_metadata.get('confidence', 0)
                confidence_indicator = "မြင့်မားသည်" if confidence >= 0.8 else "အလယ်အလတ်" if confidence >= 0.5 else "နိမ့်သည်"
                
                with open(cover_path, 'rb') as photo_file:
                    photo_data = photo_file.read()

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ ဟုတ်ကဲ့", callback_data="cover_yes"),
                     InlineKeyboardButton(text="❌ မဟုတ်ဘူး", callback_data="cover_no")]
                ])

                await message.answer_photo(
                    photo=BufferedInputFile(photo_data, filename="cover.jpg"),
                    caption=(
                        f"🎨 **ဒီကာဗာပုံ မှန်ကန်ပါသလား?**\n\n"
                        f"**ယုံကြည်မှုအဆင့်:** {confidence_indicator}\n"
                        f"**ခေါင်းစဉ်:** {ai_metadata['title']}\n"
                        f"**အဆိုတော်:** {ai_metadata['artist']}\n"
                        f"**အယ်လ်ဘမ်:** {ai_metadata['album']}"
                    ),
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )

                enhanced_query = f"{ai_metadata['title']} {ai_metadata['artist']} song"
                await state.update_data(cover_url=cover_url, cover_path=cover_path, download_query=enhanced_query, **ai_metadata)
                await state.set_state(MusicStates.confirm_cover)
                return

        await message.answer(f"🎵 ဒေတာဘေ့စ်မှာ ကာဗာပုံမတွေ့ပါ။ YouTube မှ ရယူနေပါပြီ...")
        
        download_query = f"{ai_metadata['title']} {ai_metadata['artist']} song"
        try:
            file_path, thumbnail_url, raw_metadata = await download_audio(download_query)
            
            if thumbnail_url:
                cover_path = await download_and_process_cover(thumbnail_url)
                if cover_path:
                    confidence = ai_metadata.get('confidence', 0)
                    confidence_indicator = "မြင့်မားသည်" if confidence >= 0.8 else "အလယ်အလတ်" if confidence >= 0.5 else "နိမ့်သည်"
                    
                    with open(cover_path, 'rb') as photo_file:
                        photo_data = photo_file.read()

                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✅ ဟုတ်ကဲ့", callback_data="cover_yes"),
                         InlineKeyboardButton(text="❌ မဟုတ်ဘူး", callback_data="cover_no")]
                    ])

                    await message.answer_photo(
                        photo=BufferedInputFile(photo_data, filename="youtube_cover.jpg"),
                        caption=(
                            f"🎵 **YouTube ကာဗာပုံကို အသုံးပြုပါမယ်**\n\n"
                            f"**ယုံကြည်မှုအဆင့်:** {confidence_indicator}\n"
                            f"**ခေါင်းစဉ်:** {ai_metadata['title']}\n"
                            f"**အဆိုတော်:** {ai_metadata['artist']}\n"
                            f"**အယ်လ်ဘမ်:** {ai_metadata['album']}\n\n"
                            f"✅ အသံဖိုင် ဒေါင်းလုဒ်ပြီးပါပြီ!"
                        ),
                        reply_markup=keyboard,
                        parse_mode="Markdown"
                    )

                    await state.update_data(
                        cover_url=thumbnail_url, 
                        cover_path=cover_path, 
                        file_path=file_path,
                        original_thumbnail_url=thumbnail_url,
                        download_query=download_query,
                        **ai_metadata
                    )
                    await state.set_state(MusicStates.confirm_cover)
                    return
            
            await message.answer(
                f"⚠️ **ကာဗာပုံမရှိပါ**\n\n"
                f"**ခေါင်းစဉ်:** {ai_metadata['title']}\n"
                f"**အဆိုတော်:** {ai_metadata['artist']}\n"
                f"**အယ်လ်ဘမ်:** {ai_metadata['album']}\n\n"
                f"✅ အသံဖိုင် ဒေါင်းလုဒ်ပြီးပါပြီ! ကျေးဇူးပြု၍ စာသားပို့ပါ။"
            )
            
            await state.update_data(
                file_path=file_path,
                original_thumbnail_url=thumbnail_url,
                **ai_metadata
            )
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ ပယ်ဖျက်မည်", callback_data="cancel")]
            ])

            await message.answer(
                f"📝 **ကျေးဇူးပြု၍ စာသားပို့ပါ**\n"
                f"(စာသား သို့မဟုတ် စာသားဖိုင်ကို တွဲပို့နိုင်ပါတယ်)",
                parse_mode="Markdown",
                reply_markup=keyboard
            )

            await state.set_state(MusicStates.waiting_lyrics)
            
        except Exception as download_error:
            logging.error(f"Download error: {download_error}")
            await message.answer("❌ ဒေါင်းလုဒ်မအောင်မြင်ပါ။ နောက်တစ်ကြိမ် စမ်းကြည့်ပါ။")

    except Exception as e:
        logging.error(f"Song request error: {e}")
        try:
            await bot.delete_message(message.chat.id, search_msg.message_id)
        except:
            pass
        await message.answer("❌ အမှားတစ်ခုဖြစ်သွားပါပြီ။ ကျေးဇူးပြု၍ ပြန်စမ်းကြည့်ပါ။")

@dp.callback_query(MusicStates.confirm_cover)
async def handle_cover_confirmation(callback_query: types.CallbackQuery, state: FSMContext):
    await bot.answer_callback_query(callback_query.id)
    user_data = await state.get_data()
    attempts = user_data.get('cover_attempts', 0)

    if callback_query.data == 'cover_yes':
        await callback_query.message.edit_caption(caption="✅ ကာဗာပုံ အတည်ပြုပြီးပါပြီ! သီချင်းဒေါင်းလုဒ်လုပ်နေပါပြီ...")
        await download_and_request_lyrics(callback_query.message, state)
        return

    attempts += 1
    await state.update_data(cover_attempts=attempts)

    if attempts < 3:
        await callback_query.message.edit_caption(
            caption=f"🔄 အခြားကာဗာပုံကို ရှာဖွေနေပါပြီ (အကြိမ် {attempts}/3)..."
        )
        
        cover_search_query = f"{user_data['title']} {user_data['artist']} album art official"
        cover_url, metadata = await search_cover_art(cover_search_query)

        if not cover_url:
            cover_url, metadata = await get_youtube_cover(user_data['song_query'])

        if cover_url:
            cover_path = await download_and_process_cover(cover_url)
            if cover_path:
                old_cover = user_data.get('cover_path')
                if old_cover and os.path.exists(old_cover):
                    try:
                        os.unlink(old_cover)
                    except:
                        pass

                with open(cover_path, 'rb') as photo_file:
                    photo_data = photo_file.read()

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ ဟုတ်ကဲ့", callback_data="cover_yes"),
                     InlineKeyboardButton(text="❌ မဟုတ်ဘူး", callback_data="cover_no")]
                ])

                await callback_query.message.answer_photo(
                    photo=BufferedInputFile(photo_data, filename="cover.jpg"),
                    caption=f"🎨 **ဒီပုံ ပိုကောင်းပါသလား?** (အကြိမ် {attempts}/3)\n\n"
                            f"**ခေါင်းစဉ်:** {user_data.get('title', 'Unknown')}\n"
                            f"**အဆိုတော်:** {user_data.get('artist', 'Unknown')}\n",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )

                await state.update_data(cover_url=cover_url, cover_path=cover_path)
                return

        await callback_query.message.answer("❌ အခြားကာဗာပုံမတွေ့ပါ။ YouTube ကာဗာပုံကို သုံးပါမယ်...")
        await use_youtube_thumbnail(callback_query, state)
        return

    else:
        await callback_query.message.answer("⏰ **အကြိမ် ၃ ကြိမ်ထိ ရှာပြီးပါပြီ။** YouTube ကာဗာပုံကို သုံးပါမယ်...")
        await use_youtube_thumbnail(callback_query, state)

async def use_youtube_thumbnail(callback_query: types.CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    song_query = user_data.get('song_query', '')
    download_query = user_data.get('download_query', song_query)
    
    existing_file = user_data.get('file_path')
    original_thumbnail = user_data.get('original_thumbnail_url')
    
    if existing_file and original_thumbnail:
        logging.info(f"Reusing existing file and thumbnail: {original_thumbnail}")
        thumbnail_url = original_thumbnail
        download_needed = False
    else:
        logging.info("Downloading video to get thumbnail...")
        try:
            file_path, thumbnail_url, raw_metadata = await download_audio(download_query)
            await state.update_data(
                file_path=file_path,
                original_thumbnail_url=thumbnail_url
            )
            download_needed = False
        except Exception as e:
            logging.error(f"Download failed in thumbnail function: {e}")
            await callback_query.message.answer("❌ ဒေါင်းလုဒ်မအောင်မြင်ပါ။ နောက်တစ်ကြိမ် စမ်းကြည့်ပါ။")
            return
    
    if thumbnail_url:
        cover_path = await download_and_process_cover(thumbnail_url)
        if cover_path:
            await state.update_data(cover_url=thumbnail_url, cover_path=cover_path)
            
            try:
                with open(cover_path, 'rb') as photo_file:
                    photo_data = photo_file.read()
                
                status_text = "✅ အသံဖိုင် ဒေါင်းလုဒ်ပြီးပါပြီ!" if not download_needed else "⬇️ အသံဖိုင် ဒေါင်းလုဒ်လုပ်နေပါပြီ..."
                
                await callback_query.message.answer_photo(
                    photo=BufferedInputFile(photo_data, filename="youtube_cover.jpg"),
                    caption=(
                        f"🎵 **YouTube ကာဗာပုံကို အသုံးပြုပါမယ်**\n\n"
                        f"**သီချင်း:** {user_data.get('title', song_query)}\n"
                        f"**အဆိုတော်:** {user_data.get('artist', 'Various Artists')}\n"
                        f"**အယ်လ်ဘမ်:** {user_data.get('album', 'Unknown Album')}\n\n"
                        f"{status_text}"
                    ),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logging.error(f"Error sending YouTube thumbnail: {e}")
                await callback_query.message.answer("✅ YouTube ကာဗာပုံကို အသုံးပြုပါမယ်။")
            
            if not download_needed:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="❌ ပယ်ဖျက်မည်", callback_data="cancel")]
                ])

                await callback_query.message.answer(
                    f"📝 **ကျေးဇူးပြု၍ စာသားပို့ပါ**\n"
                    f"(စာသား သို့မဟုတ် စာသားဖိုင်ကို တွဲပို့နိုင်ပါတယ်)",
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
                await state.set_state(MusicStates.waiting_lyrics)
            else:
                await download_and_request_lyrics(callback_query.message, state, skip_cover=True)
            return
        else:
            logging.error(f"Failed to process thumbnail: {thumbnail_url}")
    
    logging.error(f"No YouTube thumbnail found for query: {song_query}")
    await callback_query.message.answer("❌ ကာဗာပုံမရှိပါ။ ကာဗာပုံမပါဘဲ ဆက်လုပ်ပါမယ်။")
    
    await state.update_data(cover_url=None, cover_path=None)
    
    if not user_data.get('file_path'):
        await download_and_request_lyrics(callback_query.message, state, skip_cover=True)
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ ပယ်ဖျက်မည်", callback_data="cancel")]
        ])

        await callback_query.message.answer(
            f"📝 **ကျေးဇူးပြု၍ စာသားပို့ပါ**\n"
            f"(စာသား သို့မဟုတ် စာသားဖိုင်ကို တွဲပို့နိုင်ပါတယ်)",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        await state.set_state(MusicStates.waiting_lyrics)

async def download_and_request_lyrics(message: types.Message, state: FSMContext, skip_cover=False):
    user_data = await state.get_data()
    song_query = user_data['song_query']
    download_query = user_data.get('download_query', song_query)

    existing_file = user_data.get('file_path')
    if existing_file and os.path.exists(existing_file):
        logging.info("Using existing downloaded file")
        file_path = existing_file
        thumbnail_url = user_data.get('original_thumbnail_url')
    else:
        dl_msg = await message.answer("⬇️ အသံဖိုင် ဒေါင်းလုဒ်လုပ်နေပါပြီ...")
        
        try:
            file_path, thumbnail_url, raw_metadata = await download_audio(download_query)
            await bot.delete_message(message.chat.id, dl_msg.message_id)
        except Exception as e:
            logging.error(f"Download error: {e}")
            await bot.delete_message(message.chat.id, dl_msg.message_id)
            await message.answer("❌ ဒေါင်းလုဒ်မအောင်မြင်ပါ။ နောက်တစ်ကြိမ် စမ်းကြည့်ပါ။")
            return

    parsed_metadata = {
        'artist': user_data.get('artist', 'Various Artists'),
        'title': user_data.get('title', song_query),
        'album': user_data.get('album', 'Unknown Album')
    }

    await state.update_data(
        file_path=file_path,
        artist=parsed_metadata['artist'],
        title=parsed_metadata['title'],
        album=parsed_metadata['album'],
        original_thumbnail_url=thumbnail_url
    )

    if not skip_cover and not user_data.get('cover_path') and thumbnail_url:
        cover_path = await download_and_process_cover(thumbnail_url)
        if cover_path:
            await state.update_data(cover_url=thumbnail_url, cover_path=cover_path)
            
            with open(cover_path, 'rb') as photo_file:
                photo_data = photo_file.read()

            await message.answer_photo(
                photo=BufferedInputFile(photo_data, filename="cover.jpg"),
                caption=(
                    f"🎵 **ဒေါင်းလုဒ်အောင်မြင်ပါပြီ!**\n\n"
                    f"**သီချင်း:** {parsed_metadata['title']}\n"
                    f"**အဆိုတော်:** {parsed_metadata['artist']}\n"
                    f"**အယ်လ်ဘမ်:** {parsed_metadata['album']}"
                ),
                parse_mode="Markdown"
            )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ ပယ်ဖျက်မည်", callback_data="cancel")]
    ])

    await message.answer(
        f"📥 **စာသားအတွက် အဆင်သင့်ဖြစ်ပါပြီ!**\n\n"
        f"**သီချင်း:** {parsed_metadata['title']}\n"
        f"**အဆိုတော်:** {parsed_metadata['artist']}\n"
        f"**အယ်လ်ဘမ်:** {parsed_metadata['album']}\n\n"
        f"📝 **ကျေးဇူးပြု၍ စာသားပို့ပါ**\n"
        f"(စာသား သို့မဟုတ် စာသားဖိုင်ကို တွဲပို့နိုင်ပါတယ်)",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

    await state.set_state(MusicStates.waiting_lyrics)

@dp.message(MusicStates.waiting_lyrics)
async def handle_user_lyrics(message: types.Message, state: FSMContext):
    if message.text and message.text.startswith('/cancel'):
        await cancel_command(message, state)
        return

    if message.document and message.document.mime_type == 'text/plain':
        try:
            file = await bot.get_file(message.document.file_id)
            file_content = await bot.download_file(file.file_path)
            lyrics = file_content.read().decode('utf-8').strip()
        except Exception as e:
            logging.error(f"File read error: {e}")
            await message.answer("ဖိုင်ဖတ်ရာမှာ အဆင်မပြေပါ။ ကျေးဇူးပြု၍ စာသားကို တိုက်ရိုက်ကူးထည့်ပါ။")
            return
    elif message.text:
        lyrics = message.text.strip()
    else:
        await message.answer("ကျေးဇူးပြု၍ စာသား သို့မဟုတ် စာသားဖိုင် တွဲပို့ပါ။")
        return

    if len(lyrics) < 20:
        await message.answer("စာသားက သိပ်တိုနေပါတယ်။ ကျေးဇူးပြု၍ အပြည့်အစုံ ပို့ပါ။")
        return

    await process_lyrics(message, state, lyrics)

@dp.callback_query(MusicStates.waiting_lyrics)
async def handle_lyrics_cancel(callback_query: types.CallbackQuery, state: FSMContext):
    if callback_query.data == 'cancel':
        await bot.answer_callback_query(callback_query.id)
        user_data = await state.get_data()
        await cleanup_user_files(user_data)
        await state.clear()
        await callback_query.message.answer("လုပ်ဆောင်မှုကို ပယ်ဖျက်လိုက်ပါပြီ။ ပြန်စရန် /start ကိုသုံးပါ။")

async def process_lyrics(message: types.Message, state: FSMContext, lyrics: str):
    user_data = await state.get_data()
    processing_msg = await message.answer("🎵 သီချင်းကို စီမံဆောင်ရွက်နေပါပြီ...")

    try:
        artist = user_data.get('artist', 'Various Artists')
        album = user_data.get('album', 'Unknown Album')
        title = user_data.get('title', user_data['song_query'])
        cover_path = user_data.get('cover_path')

        final_path = await embed_metadata(
            user_data['file_path'],
            lyrics,
            artist,
            album,
            title,
            cover_path
        )

        try:
            audio = MP3(final_path)
            duration = int(audio.info.length) if audio.info.length else 0
        except:
            duration = 0

        file_size = os.path.getsize(final_path)
        
        if file_size < 50 * 1024 * 1024:
            try:
                thumbnail_data = None
                if cover_path and os.path.exists(cover_path):
                    try:
                        with open(cover_path, 'rb') as thumb_file:
                            thumbnail_data = BufferedInputFile(thumb_file.read(), filename="thumb.jpg")
                    except:
                        thumbnail_data = None

                final_file = FSInputFile(final_path, filename=f"{title}.mp3")
                
                await message.answer_audio(
                    audio=final_file,
                    title=title,
                    performer=artist,
                    duration=duration,
                    thumbnail=thumbnail_data,
                    caption=(
                        f"🎵 **{title}** - **{artist}**\n\n"
                        f"📀 **အယ်လ်ဘမ်:** {album}\n"
                        f"📝 **စာသား ထည့်သွင်းပြီးပါပြီ**\n"
                        f"🏷️ **Metadata ထည့်သွင်းပြီးပါပြီ**\n"
                        f"📱 **Samsung Music နဲ့ သုံးလို့ရပါပြီ**\n\n"
                        f"🎧 **Telegram မှာ တိုက်ရိုက်နားဆင်ရန် နှိပ်ပါ!**"
                    ),
                    parse_mode="Markdown"
                )
                
            except Exception as audio_error:
                logging.error(f"Audio send error: {audio_error}")
                final_file = FSInputFile(final_path, filename=f"{title}.mp3")
                await message.answer_document(
                    document=final_file,
                    caption=f"🎵 **{title}** - **{artist}** (ဒေါင်းလုဒ်ဆွဲပြီး နားဆင်ပါ)",
                    parse_mode="Markdown"
                )
        else:
            final_file = FSInputFile(final_path, filename=f"{title}.mp3")
            await message.answer_document(
                document=final_file,
                caption=f"🎵 **{title}** - **{artist}** (ဖိုင်အရွယ်အစားကြီးလို့ Telegram မှာ တိုက်ရိုက်ဖွင့်မရပါ)",
                parse_mode="Markdown"
            )

        await cleanup_user_files(user_data)
        if os.path.exists(final_path):
            try:
                os.unlink(final_path)
            except:
                pass

        await bot.delete_message(message.chat.id, processing_msg.message_id)
        await state.clear()

    except Exception as e:
        logging.error(f"Processing error: {e}")
        await bot.delete_message(message.chat.id, processing_msg.message_id)
        await message.answer("❌ စီမံဆောင်ရွက်ရာမှာ အဆင်မပြေပါ။ နောက်တစ်ကြိမ် စမ်းကြည့်ပါ။")
        await state.clear()

@dp.message()
async def handle_general_message(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    
    if current_state is None:
        if message.text and not message.text.startswith('/'):
            await state.update_data(song_query=message.text.strip())
            await state.set_state(MusicStates.waiting_song)
            await handle_song_request(message, state)
        else:
            await message.answer("စတင်ရန် /start ကိုသုံးပါ၊ အကူအညီအတွက် /help ကိုသုံးပါ!")

# ================== HELPER FUNCTIONS ================== #
async def search_cover_art(query):
    try:
        params = {'term': query, 'media': 'music', 'limit': 3}
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(config.ITUNES_API, params=params, timeout=10, headers=headers)
        if response.status_code == 200:
            data = response.json()
            for result in data.get('results', []):
                cover_url = result['artworkUrl100'].replace('100x100', '600x600')
                return cover_url, {
                    'artist': result['artistName'],
                    'album': result['collectionName'],
                    'title': result['trackName']
                }

        params = {'q': query}
        response = requests.get(config.DEEZER_API, params=params, timeout=10, headers=headers)
        if response.status_code == 200:
            data = response.json()
            for track in data.get('data', [])[:3]:
                cover_url = track['album']['cover_xl']
                return cover_url, {
                    'artist': track['artist']['name'],
                    'album': track['album']['title'],
                    'title': track['title']
                }

    except Exception as e:
        logging.error(f"Cover search error: {e}")
    
    return None, {}

async def get_youtube_cover(query):
    try:
        s = Search(query)
        if not s.videos:
            return None, {}

        video = s.videos[0]
        thumbnail = video.thumbnail_url
        if thumbnail:
            if 'maxresdefault' not in thumbnail:
                thumbnail = thumbnail.replace('hqdefault', 'maxresdefault')
            return thumbnail, {}

        return None, {}
    except Exception as e:
        logging.warning(f"YouTube cover skipped (non-critical): {e}")
        return None, {}

async def download_and_process_cover(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        
        response = None
        try:
            response = requests.get(url, timeout=15, headers=headers, stream=True)
            logging.info(f"Thumbnail response status: {response.status_code}")
            
            if response.status_code != 200:
                if 'maxresdefault' in url:
                    fallback_url = url.replace('maxresdefault', 'hqdefault')
                    logging.info(f"Trying fallback URL: {fallback_url}")
                    response = requests.get(fallback_url, timeout=15, headers=headers, stream=True)
                
                if response.status_code != 200:
                    logging.error(f"HTTP {response.status_code} for thumbnail: {url}")
                    return None
                    
        except requests.RequestException as e:
            logging.error(f"Network error downloading thumbnail: {e}")
            return None

        content_type = response.headers.get('content-type', '')
        if not content_type.startswith('image/'):
            logging.error(f"Invalid content type: {content_type} for URL: {url}")
            return None

        image_content = response.content
        if len(image_content) < 1000:
            logging.error(f"Image too small ({len(image_content)} bytes): {url}")
            return None

        try:
            img = Image.open(BytesIO(image_content))
            if img.mode in ['RGBA', 'LA', 'P']:
                img = img.convert('RGB')
            if img.width > 1000 or img.height > 1000:
                img.thumbnail((1000, 1000), Image.Resampling.LANCZOS)
            if img.width < 200 or img.height < 200:
                img = img.resize((300, 300), Image.Resampling.LANCZOS)

            os.makedirs('covers', exist_ok=True)
            cover_path = f"covers/{uuid.uuid4().hex}.jpg"
            img.save(cover_path, format='JPEG', quality=90, optimize=True)
            
            if os.path.exists(cover_path) and os.path.getsize(cover_path) > 1000:
                logging.info(f"Successfully processed thumbnail: {cover_path}")
                return cover_path
            else:
                logging.error(f"File creation failed: {cover_path}")
                return None
                
        except UnidentifiedImageError:
            logging.error(f"Invalid image format from URL: {url}")
            return None
        except Exception as img_error:
            logging.error(f"Image processing error: {img_error}")
            return None

    except Exception as e:
        logging.error(f"Cover processing error for {url}: {e}")
        return None

async def download_audio(query):
    import asyncio
    import uuid
    import yt_dlp
    
    safe_query = re.sub(r'[\\/*?:"<>|]', "", query)[:50]
    unique_id = uuid.uuid4().hex[:8]
    thumbnail_url = None

    os.makedirs("downloads", exist_ok=True)

    outtmpl = f"downloads/{safe_query}_{unique_id}.%(ext)s"

    def _find_output_file(entry, safe_q, uid):
        requested = entry.get('requested_downloads', [])
        if requested:
            final_path = requested[0].get('filepath')
            if final_path and os.path.exists(final_path) and os.path.getsize(final_path) > 0:
                logging.info(f"Found via requested_downloads: {final_path}")
                return final_path

        mp3_path = f"downloads/{safe_q}_{uid}.mp3"
        if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
            logging.info(f"Found via expected path: {mp3_path}")
            return mp3_path
            
        for fp in glob.glob(f"downloads/{safe_q}_{uid}.*"):
            if os.path.getsize(fp) > 0:
                logging.info(f"Found via glob: {fp}")
                return fp

        all_files = glob.glob("downloads/*.*")
        if all_files:
            newest = max(all_files, key=os.path.getmtime)
            if os.path.getsize(newest) > 0:
                logging.info(f"Found via newest fallback: {newest}")
                return newest
        return None

    def _extract_metadata(entry, fallback_query, source_name):
        title = entry.get('title', fallback_query)
        artist = entry.get('uploader', 'Unknown Artist')
        thumb = entry.get('thumbnail')
        meta = {'artist': artist, 'title': title, 'album': source_name}
        return title, artist, thumb, meta

    # ======== LAYER 1: YouTube ========
    try:
        logging.info(f"[Layer 1] Attempting YouTube download for: {query}")

        yt_urls = [f"ytsearch1:{query}"]

        yt_opts = {
            'format': 'bestaudio*/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': outtmpl,
            'quiet': True,
            'noplaylist': True,
            'no_warnings': True,
            'socket_timeout': 30,
            'retries': 2,
            'source_address': '0.0.0.0',
            'cookiefile': config.COOKIES_FILE,
            'logger': YTDLLogger(),
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            },
            'extractor_args': {
                'youtube': {
                    'player_client': ['mweb', 'tv'],
                }
            },
            'remote_components': ['ejs:github'],
        }

        if NODE_BIN:
            yt_opts['js_runtimes'] = {'node': {'path': NODE_BIN}}

        if _pot_server_process is not None:
            yt_opts.setdefault('extractor_args', {})['youtubepot-bgutilhttp'] = {
                'base_url': ['http://127.0.0.1:4416']
            }

        try:
            import subprocess
            _ejs_check = subprocess.run(
                ['yt-dlp', '--remote-components', 'ejs:github', '--version'],
                capture_output=True, text=True, timeout=30
            )
            logging.info(f"EJS pre-download: rc={_ejs_check.returncode}")
        except Exception:
            pass

        for yt_url in yt_urls:
            try:
                def run_yt():
                    with yt_dlp.YoutubeDL(yt_opts) as ydl:
                        return ydl.extract_info(yt_url, download=True)

                info = await asyncio.to_thread(run_yt)

                if info and 'entries' in info:
                    entry = (info.get('entries') or [{}])[0] or {}
                else:
                    entry = info or {}

                title, artist, thumb, meta = _extract_metadata(entry, query, 'YouTube')
                if thumb:
                    thumbnail_url = thumb

                logging.info(f"[Layer 1] YouTube extracted: {title}")

                found = _find_output_file(entry, safe_query, unique_id)
                if found:
                    return found, thumbnail_url, meta

            except Exception as yt_err:
                logging.warning(f"[Layer 1] YouTube failed for {yt_url}: {str(yt_err)[:120]}")
                continue

        logging.warning("[Layer 1] All YouTube URLs exhausted. Falling back to SoundCloud...")

    except Exception as layer1_err:
        logging.warning(f"[Layer 1] YouTube layer crashed: {layer1_err}")

    # ======== LAYER 2: SoundCloud Fallback ========
    try:
        logging.info(f"[Layer 2] Attempting SoundCloud download for: {query}")

        unique_id_sc = uuid.uuid4().hex[:8]
        outtmpl_sc = f"downloads/{safe_query}_{unique_id_sc}.%(ext)s"

        sc_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': outtmpl_sc,
            'quiet': True,
            'noplaylist': True,
            'no_warnings': True,
            'socket_timeout': 30,
            'retries': 3,
            'source_address': '0.0.0.0',
            'logger': YTDLLogger(),
        }

        def run_sc():
            with yt_dlp.YoutubeDL(sc_opts) as ydl:
                return ydl.extract_info(f"scsearch1:{query}", download=True)

        info = await asyncio.to_thread(run_sc)

        if info and 'entries' in info:
            entry = (info.get('entries') or [{}])[0] or {}
        else:
            entry = info or {}

        title, artist, thumb, meta = _extract_metadata(entry, query, 'SoundCloud')
        if thumb:
            thumbnail_url = thumb

        logging.info(f"[Layer 2] SoundCloud extracted: {title}")

        found = _find_output_file(entry, safe_query, unique_id_sc)
        if found:
            return found, thumbnail_url, meta

        raise Exception("SoundCloud download succeeded but MP3 file not found on disk.")

    except Exception as layer2_err:
        logging.error(f"[Layer 2] SoundCloud also failed: {layer2_err}")
        raise Exception(f"All download layers failed for '{query}'. YouTube and SoundCloud both exhausted.")

async def embed_metadata(file_path, lyrics, artist, album, title, cover_path=None):
    try:
        audio = MP3(file_path, ID3=ID3)
        
        try:
            audio.add_tags()
        except Exception:
            pass

        audio.tags.add(TIT2(encoding=Encoding.UTF16, text=title))
        audio.tags.add(TPE1(encoding=Encoding.UTF16, text=artist))
        audio.tags.add(TALB(encoding=Encoding.UTF16, text=album))
        audio.tags.add(USLT(encoding=Encoding.UTF16, lang='eng', desc='Lyrics', text=lyrics))

        if cover_path and os.path.exists(cover_path):
            try:
                with open(cover_path, 'rb') as f:
                    cover_data = f.read()
                    
                audio.tags.add(APIC(
                    encoding=3,
                    mime='image/jpeg',
                    type=3,
                    desc='Cover',
                    data=cover_data
                ))
            except Exception as e:
                logging.error(f"Cover embedding error: {e}")

        audio.save()

        final_filename = re.sub(r'[\\/*?:"<>|]', "", f"{artist} - {title}.mp3")
        final_path = f"processed/{final_filename}"
        
        os.makedirs('processed', exist_ok=True)
        shutil.move(file_path, final_path)
        
        return final_path

    except Exception as e:
        logging.error(f"Metadata embedding error: {e}")
        raise Exception(f"Failed to embed metadata: {str(e)}")

@dp.errors()
async def error_handler(event, exception):
    logging.error(f"Error: {exception}", exc_info=True)
    
    if hasattr(event, 'message') and event.message:
        try:
            await event.message.answer("မမျှော်လင့်ထားတဲ့ အမှားတစ်ခုဖြစ်သွားပါပြီ။ ကျေးဇူးပြု၍ ပြန်စမ်းကြည့်ပါ။")
        except:
            pass
    elif hasattr(event, 'callback_query') and event.callback_query:
        try:
            await event.callback_query.message.answer("မမျှော်လင့်ထားတဲ့ အမှားတစ်ခုဖြစ်သွားပါပြီ။ ကျေးဇူးပြု၍ ပြန်စမ်းကြည့်ပါ။")
        except:
            pass
    
    return True

async def main():
    if os.environ.get('RENDER'):
        WEBHOOK_HOST = os.getenv('RENDER_EXTERNAL_URL', 'https://your-app-name.onrender.com')
        WEBHOOK_PATH = f"/webhook/{config.TOKEN}"
        WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
        
        await bot.set_webhook(WEBHOOK_URL)
        
        app = web.Application()
        webhook_requests_handler = SimpleRequestHandler(
            dispatcher=dp,
            bot=bot,
        )
        webhook_requests_handler.register(app, path=WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)
        
        async def health_check(request):
            return web.Response(text="Bot is running!")
        
        app.router.add_get('/', health_check)
        
        port = int(os.environ.get("PORT", 8000))
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        
        logging.info(f"Bot started on port {port}")
        logging.info(f"Webhook URL: {WEBHOOK_URL}")
        
        try:
            await asyncio.Event().wait()
        finally:
            await runner.cleanup()
    else:
        logging.info("Starting bot in local polling mode...")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped")
