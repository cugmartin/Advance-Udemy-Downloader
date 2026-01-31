# -*- coding: utf-8 -*-
import argparse
import copy
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import IO, Union, Optional

import browser_cookie3
import demoji
import m3u8
import requests
import yt_dlp
from bs4 import BeautifulSoup
from coloredlogs import ColoredFormatter
from dotenv import load_dotenv
from pathvalidate import sanitize_filename
from requests.exceptions import ConnectionError as conn_error
from tqdm import tqdm

from constants import *
from tls import SSLCiphers
from utils import extract_kid
from vtt_to_srt import convert
from translator import create_translator

DOWNLOAD_DIR = os.path.join(os.getcwd(), "out_dir")
TEMP_DIR = os.path.join(os.getcwd(), "temp")

retry = 3
downloader = None
logger: logging.Logger = None
dl_assets = False
dl_captions = False
dl_quizzes = False
skip_lectures = False
caption_locale = "en"
quality = None
bearer_token = None
portal_name = None
course_name = None
keep_vtt = False
skip_hls = False
concurrent_downloads = 10
save_to_file = None
load_from_file = None
course_url = None
info = None
keys = {}
id_as_course_name = False
is_subscription_course = False
use_h265 = False
h265_crf = 28
h265_preset = "medium"
use_nvenc = False
translator = None
auto_translate = False
translation_executor = None
translation_futures = []
translation_lock = threading.Lock()
browser = None
cj = None
use_continuous_lecture_numbers = False
chapter_filter = None
YTDLP_PATH = None
ARIA2C_DOWNLOADER_ARGS = "aria2c:--disable-ipv6 --connect-timeout=10 --timeout=30 --retry-wait=2 --max-tries=20 --max-connection-per-server=4"
STRICT_MODE = False
DISABLE_PROXY = False
STRICT_FAILURES = []
FAILED_DOWNLOAD_RETRY_LIMIT = 1


def _curl_cffi_get(url: str, headers: dict, cookies, timeout: tuple[int, int]):
    try:
        from curl_cffi import requests as c_requests
    except Exception:
        return None

    proxies = None
    if not DISABLE_PROXY:
        https_proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
        http_proxy = os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
        if https_proxy or http_proxy:
            proxies = {}
            if http_proxy:
                proxies["http"] = http_proxy
            if https_proxy:
                proxies["https"] = https_proxy

    try:
        return c_requests.request(
            "GET",
            url,
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            proxies=proxies,
            impersonate="chrome",
        )
    except Exception:
        return None


def _raise_for_status(resp, url: str):
    if resp is None:
        raise Exception(f"No response for {url}")
    raise_fn = getattr(resp, "raise_for_status", None)
    if callable(raise_fn):
        raise_fn()
        return
    status = getattr(resp, "status_code", None)
    if status is None:
        return
    if int(status) >= 400:
        reason = getattr(resp, "reason", "")
        raise Exception(f"Failed request {url} ({status} {reason})")

def deEmojify(inputStr: str):
    return demoji.replace(inputStr, "")

def record_strict_failure(lecture_id: str, lecture_title: str, reason: str) -> None:
    if not STRICT_MODE:
        return
    try:
        STRICT_FAILURES.append({"id": str(lecture_id), "title": str(lecture_title), "reason": str(reason)})
    except Exception:
        pass


def _clear_strict_failure(lecture_id: str) -> None:
    if not STRICT_MODE or not STRICT_FAILURES:
        return
    try:
        STRICT_FAILURES[:] = [item for item in STRICT_FAILURES if item.get("id") != str(lecture_id)]
    except Exception:
        pass


def _retry_failed_downloads(failed_entries):
    if not failed_entries:
        return
    if FAILED_DOWNLOAD_RETRY_LIMIT <= 0:
        logger.warning("> Failed lecture retries disabled (limit <= 0). Skipping %d queued lecture(s).", len(failed_entries))
        return

    attempt = 1
    pending = failed_entries

    while pending and attempt <= FAILED_DOWNLOAD_RETRY_LIMIT:
        logger.info("> Retrying %d failed lecture(s) (attempt %d/%d)...", len(pending), attempt, FAILED_DOWNLOAD_RETRY_LIMIT)
        next_round = []
        for entry in pending:
            lecture_path = entry["lecture_path"]
            lecture_title = entry["lecture_title"]
            lecture_id = entry["lecture_id"]
            chapter_dir = entry["chapter_dir"]
            lecture_data = copy.deepcopy(entry["lecture_data"])

            try:
                process_lecture(lecture_data, lecture_path, chapter_dir)
            except Exception:
                logger.exception("    > Retry attempt raised an exception for lecture '%s'", lecture_title)

            if os.path.isfile(lecture_path):
                logger.info("    > Retry succeeded (%s)", lecture_title)
                _clear_strict_failure(lecture_id)
            else:
                next_round.append(entry)
        pending = next_round
        attempt += 1

    if pending:
        logger.warning("> %d lecture(s) still failed after %d retry attempt(s).", len(pending), FAILED_DOWNLOAD_RETRY_LIMIT)
        for entry in pending:
            logger.warning("    > Still missing: %s (%s)", entry["lecture_title"], entry["lecture_id"])

# from https://stackoverflow.com/a/21978778/9785713
def log_subprocess_output(prefix: str, pipe: IO[bytes]):
    if pipe:
        for line in iter(lambda: pipe.read(1), ""):
            logger.debug("[%s]: %r", prefix, line.decode("utf8").strip())
        pipe.flush()


def parse_chapter_filter(chapter_str: str):
    """
    Given a string like "1,3-5,7,9-11", return a set of chapter numbers.
    """
    chapters = set()
    for part in chapter_str.split(","):
        if "-" in part:
            try:
                start, end = part.split("-")
                start = int(start.strip())
                end = int(end.strip())
                chapters.update(range(start, end + 1))
            except ValueError:
                logger.error("Invalid range in --chapter argument: %s", part)
        else:
            try:
                chapters.add(int(part.strip()))
            except ValueError:
                logger.error("Invalid chapter number in --chapter argument: %s", part)
    return chapters


# this is the first function that is called, we parse the arguments, setup the logger, and ensure that required directories exist
def pre_run():
    global dl_assets, dl_captions, dl_quizzes, skip_lectures, caption_locale, quality, bearer_token, course_name, keep_vtt, skip_hls, concurrent_downloads, load_from_file, save_to_file, bearer_token, course_url, info, logger, keys, id_as_course_name, LOG_LEVEL, use_h265, h265_crf, h265_preset, use_nvenc, browser, is_subscription_course, DOWNLOAD_DIR, use_continuous_lecture_numbers, chapter_filter, translator, auto_translate, STRICT_MODE, DISABLE_PROXY

    # Load environment variables first
    load_dotenv()

    HEADERS["User-Agent"] = os.getenv(
        "UDEMY_USER_AGENT",
        HEADERS.get(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ),
    )
    CURRICULUM_ITEMS_PARAMS["page_size"] = os.getenv("UDEMY_CURRICULUM_PAGE_SIZE", "200")
    
    # make sure the logs directory exists
    if not os.path.exists(LOG_DIR_PATH):
        os.makedirs(LOG_DIR_PATH, exist_ok=True)

    parser = argparse.ArgumentParser(description="Udemy Downloader")
    parser.add_argument(
        "-c", "--course-url", dest="course_url", type=str, help="The URL of the course to download", required=True
    )
    parser.add_argument(
        "-b",
        "--bearer",
        dest="bearer_token",
        type=str,
        help="The Bearer token to use",
    )
    parser.add_argument(
        "-q",
        "--quality",
        dest="quality",
        type=int,
        help="Download specific video quality. If the requested quality isn't available, the closest quality will be used. If not specified, the best quality will be downloaded for each lecture",
    )
    parser.add_argument(
        "-l",
        "--lang",
        dest="lang",
        type=str,
        help="The language to download for captions, specify 'all' to download all captions (Default is 'en')",
    )
    parser.add_argument(
        "-cd",
        "--concurrent-downloads",
        dest="concurrent_downloads",
        type=int,
        help="The number of maximum concurrent downloads for segments (HLS and DASH, must be a number 1-30)",
    )
    parser.add_argument(
        "--skip-lectures",
        dest="skip_lectures",
        action="store_true",
        help="If specified, lectures won't be downloaded",
    )
    parser.add_argument(
        "--download-assets",
        dest="download_assets",
        action="store_true",
        help="If specified, lecture assets will be downloaded",
    )
    parser.add_argument(
        "--download-captions",
        dest="download_captions",
        action="store_true",
        help="If specified, captions will be downloaded",
    )
    parser.add_argument(
        "--download-quizzes",
        dest="download_quizzes",
        action="store_true",
        help="If specified, quizzes will be downloaded",
    )
    parser.add_argument(
        "--keep-vtt",
        dest="keep_vtt",
        action="store_true",
        help="If specified, .vtt files won't be removed",
    )
    parser.add_argument(
        "--skip-hls",
        dest="skip_hls",
        action="store_true",
        help="If specified, hls streams will be skipped (faster fetching) (hls streams usually contain 1080p quality for non-drm lectures)",
    )
    parser.add_argument(
        "--info",
        dest="info",
        action="store_true",
        help="If specified, only course information will be printed, nothing will be downloaded",
    )
    parser.add_argument(
        "--id-as-course-name",
        dest="id_as_course_name",
        action="store_true",
        help="If specified, the course id will be used in place of the course name for the output directory. This is a 'hack' to reduce the path length",
    )
    parser.add_argument(
        "-sc",
        "--subscription-course",
        dest="is_subscription_course",
        action="store_true",
        help="Mark the course as a subscription based course, use this if you are having problems with the program auto detecting it",
    )
    parser.add_argument(
        "--save-to-file",
        dest="save_to_file",
        action="store_true",
        help="If specified, course content will be saved to a file that can be loaded later with --load-from-file, this can reduce processing time (Note that asset links expire after a certain amount of time)",
    )
    parser.add_argument(
        "--load-from-file",
        dest="load_from_file",
        action="store_true",
        help="If specified, course content will be loaded from a previously saved file with --save-to-file, this can reduce processing time (Note that asset links expire after a certain amount of time)",
    )
    parser.add_argument(
        "--log-level",
        dest="log_level",
        type=str,
        help="Logging level: one of DEBUG, INFO, ERROR, WARNING, CRITICAL (Default is INFO)",
    )
    parser.add_argument(
        "--browser",
        dest="browser",
        help="The browser to extract cookies from",
        choices=["chrome", "firefox", "opera", "edge", "brave", "chromium", "vivaldi", "safari", "file"],
    )
    parser.add_argument(
        "--use-h265",
        dest="use_h265",
        action="store_true",
        help="If specified, videos will be encoded with the H.265 codec",
    )
    parser.add_argument(
        "--h265-crf",
        dest="h265_crf",
        type=int,
        default=28,
        help="Set a custom CRF value for H.265 encoding. FFMPEG default is 28",
    )
    parser.add_argument(
        "--h265-preset",
        dest="h265_preset",
        type=str,
        default="medium",
        help="Set a custom preset value for H.265 encoding. FFMPEG default is medium",
    )
    parser.add_argument(
        "--use-nvenc",
        dest="use_nvenc",
        action="store_true",
        help="Whether to use the NVIDIA hardware transcoding for H.265. Only works if you have a supported NVIDIA GPU and ffmpeg with nvenc support",
    )
    parser.add_argument(
        "--out",
        "-o",
        dest="out",
        type=str,
        help="Set the path to the output directory",
    )
    parser.add_argument(
        "--continue-lecture-numbers",
        "-n",
        dest="use_continuous_lecture_numbers",
        action="store_true",
        help="Use continuous lecture numbering instead of per-chapter",
    )
    parser.add_argument(
        "--chapter",
        dest="chapter_filter_raw",
        type=str,
        help="Download specific chapters. Use comma separated values and ranges (e.g., '1,3-5,7,9-11').",
    )
    parser.add_argument(
        "--strict",
        dest="strict",
        action="store_true",
        help="If specified, any lecture download failure will cause the program to exit with code 1",
    )
    parser.add_argument(
        "--no-proxy",
        dest="no_proxy",
        action="store_true",
        help="If specified, disable system/environment proxy settings for network requests",
    )
    # parser.add_argument("-v", "--version", action="version", version="You are running version {version}".format(version=__version__))

    args = parser.parse_args()
    if args.download_assets:
        dl_assets = True
    if args.lang:
        caption_locale = args.lang
    if args.download_captions:
        dl_captions = True
    if args.download_quizzes:
        dl_quizzes = True
    if args.skip_lectures:
        skip_lectures = True
    if args.quality:
        quality = args.quality
    if args.keep_vtt:
        keep_vtt = args.keep_vtt
    if args.skip_hls:
        skip_hls = args.skip_hls
    if args.concurrent_downloads:
        concurrent_downloads = args.concurrent_downloads

        if concurrent_downloads <= 0:
            # if the user gave a number that is less than or equal to 0, set cc to default of 10
            concurrent_downloads = 10
        elif concurrent_downloads > 30:
            # if the user gave a number thats greater than 30, set cc to the max of 30
            concurrent_downloads = 30
    if args.load_from_file:
        load_from_file = args.load_from_file
    if args.save_to_file:
        save_to_file = args.save_to_file
    if args.bearer_token:
        bearer_token = args.bearer_token
    if args.course_url:
        course_url = args.course_url
    if args.info:
        info = args.info
    if args.use_h265:
        use_h265 = True
    if args.h265_crf:
        h265_crf = args.h265_crf
    if args.h265_preset:
        h265_preset = args.h265_preset
    if args.use_nvenc:
        use_nvenc = True
    if args.log_level:
        if args.log_level.upper() == "DEBUG":
            LOG_LEVEL = logging.DEBUG
        elif args.log_level.upper() == "INFO":
            LOG_LEVEL = logging.INFO
        elif args.log_level.upper() == "ERROR":
            LOG_LEVEL = logging.ERROR
        elif args.log_level.upper() == "WARNING":
            LOG_LEVEL = logging.WARNING
        elif args.log_level.upper() == "CRITICAL":
            LOG_LEVEL = logging.CRITICAL
        else:
            print(f"Invalid log level: {args.log_level}; Using INFO")
            LOG_LEVEL = logging.INFO
    if args.id_as_course_name:
        id_as_course_name = args.id_as_course_name
    if args.is_subscription_course:
        is_subscription_course = args.is_subscription_course
    if args.browser:
        browser = args.browser
    if args.out:
        DOWNLOAD_DIR = os.path.abspath(args.out)
    if args.use_continuous_lecture_numbers:
        use_continuous_lecture_numbers = args.use_continuous_lecture_numbers
    if args.chapter_filter_raw:
        chapter_filter = parse_chapter_filter(args.chapter_filter_raw)
        logging.getLogger("udemy-downloader").info("Chapter filter applied: %s", sorted(chapter_filter))
    if getattr(args, "strict", False) or os.getenv("STRICT_MODE", "0").strip().lower() in ("1", "true", "yes"):
        STRICT_MODE = True
    if getattr(args, "no_proxy", False) or os.getenv("NO_PROXY_MODE", "0").strip().lower() in ("1", "true", "yes"):
        DISABLE_PROXY = True
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            try:
                os.environ.pop(k, None)
            except Exception:
                pass
    
    # Auto-enable captions and translation when downloading videos
    if not skip_lectures and not info:
        dl_captions = True
        caption_locale = "en"
        logger_temp = logging.getLogger("udemy-downloader")
        logger_temp.info("Auto-enabling English captions for video downloads")

        provider = os.getenv("TRANSLATE_PROVIDER")
        if provider or os.getenv("DEEPL_API_KEY"):
            try:
                translator = create_translator(provider=provider)
                auto_translate = True
                logger_temp.info("Auto-translation enabled (EN -> ZH) using provider: %s", provider or "deepl")
            except Exception as e:
                logger_temp.warning(
                    "Failed to initialize translator provider '%s': %s. Continuing without translation.",
                    provider,
                    e,
                )
                auto_translate = False
        else:
            logger_temp.info("No translator configured (set TRANSLATE_PROVIDER or DEEPL_API_KEY), translation disabled")

    # setup a logger
    logger = logging.getLogger(__name__)
    logging.root.setLevel(LOG_LEVEL)

    # create a colored formatter for the console
    console_formatter = ColoredFormatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    # create a regular non-colored formatter for the log file
    file_formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # create a handler for console logging
    stream = logging.StreamHandler()
    stream.setLevel(LOG_LEVEL)
    stream.setFormatter(console_formatter)

    # create a handler for file logging
    file_handler = logging.FileHandler(LOG_FILE_PATH)
    file_handler.setFormatter(file_formatter)

    # construct the logger
    logger = logging.getLogger("udemy-downloader")
    logger.setLevel(LOG_LEVEL)
    logger.addHandler(stream)
    logger.addHandler(file_handler)

    logger.info(f"Output directory set to {DOWNLOAD_DIR}")

    Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)
    Path(SAVED_DIR).mkdir(parents=True, exist_ok=True)

    # Get the keys
    if os.path.exists(KEY_FILE_PATH):
        with open(KEY_FILE_PATH, encoding="utf8", mode="r") as keyfile:
            keys = json.loads(keyfile.read())
    else:
        logger.warning("> Keyfile not found! You won't be able to decrypt any encrypted videos!")

    # Process the chapter filter
    if args.chapter_filter_raw:
        chapter_filter = parse_chapter_filter(args.chapter_filter_raw)
        logger.info("Chapter filter applied: %s", sorted(chapter_filter))


class Udemy:
    def __init__(self, bearer_token):
        global cj

        self.session = None
        self.bearer_token = None
        self.auth = UdemyAuth(cache_session=False)
        if not self.session:
            self.session = self.auth.authenticate(bearer_token=bearer_token)

        if not self.session:
            if browser == None:
                logger.error("No bearer token was provided, and no browser for cookie extraction was specified.")
                sys.exit(1)

            logger.warning("No bearer token was provided, attempting to use browser cookies.")

            self.session = self.auth._session

            if browser == "chrome":
                cj = browser_cookie3.chrome()
            elif browser == "firefox":
                cj = browser_cookie3.firefox()
            elif browser == "opera":
                cj = browser_cookie3.opera()
            elif browser == "edge":
                cj = browser_cookie3.edge()
            elif browser == "brave":
                cj = browser_cookie3.brave()
            elif browser == "chromium":
                cj = browser_cookie3.chromium()
            elif browser == "vivaldi":
                cj = browser_cookie3.vivaldi()
            elif browser == "file":
                # load netscape cookies from file
                cj = MozillaCookieJar("cookies.txt")
                cj.load(ignore_discard=True, ignore_expires=True)

        if cj is None and os.path.exists("cookies.txt"):
            logger.info("Found cookies.txt, attempting to use for authentication...")
            cj = MozillaCookieJar("cookies.txt")
            cj.load(ignore_discard=True, ignore_expires=True)

        if cj is None and os.path.exists("cookie.txt"):
            logger.info("Found cookie.txt, attempting to use for authentication...")
            cj = MozillaCookieJar("cookie.txt")
            cj.load(ignore_discard=True, ignore_expires=True)

    def _get_quiz(self, quiz_id):
        self.session._headers.update(
            {
                "Host": "{portal_name}.udemy.com".format(portal_name=portal_name),
                "Referer": "https://{portal_name}.udemy.com/course/{course_name}/learn/quiz/{quiz_id}".format(
                    portal_name=portal_name, course_name=course_name, quiz_id=quiz_id
                ),
            }
        )
        url = QUIZ_URL.format(portal_name=portal_name, quiz_id=quiz_id)
        try:
            resp = self.session._get(url).json()
        except conn_error as error:
            logger.fatal(f"[-] Connection error: {error}")
            time.sleep(0.8)
            sys.exit(1)
        else:
            return resp.get("results")

    def _get_elem_value_or_none(self, elem, key):
        return elem[key] if elem and key in elem else "(None)"

    def _get_quiz_with_info(self, quiz_id):
        resp = {"_class": None, "_type": None, "contents": None}
        quiz_json = self._get_quiz(quiz_id)
        is_only_one = len(quiz_json) == 1 and quiz_json[0]["_class"] == "assessment"
        is_coding_assignment = quiz_json[0]["assessment_type"] == "coding-problem"

        resp["_class"] = quiz_json[0]["_class"]

        if is_only_one and is_coding_assignment:
            assignment = quiz_json[0]
            prompt = assignment["prompt"]

            resp["_type"] = assignment["assessment_type"]

            resp["contents"] = {
                "instructions": self._get_elem_value_or_none(prompt, "instructions"),
                "tests": self._get_elem_value_or_none(prompt, "test_files"),
                "solutions": self._get_elem_value_or_none(prompt, "solution_files"),
            }

            resp["hasInstructions"] = False if resp["contents"]["instructions"] == "(None)" else True
            resp["hasTests"] = False if isinstance(resp["contents"]["tests"], str) else True
            resp["hasSolutions"] = False if isinstance(resp["contents"]["solutions"], str) else True
        else:  # Normal quiz
            resp["_type"] = "normal-quiz"
            resp["contents"] = quiz_json

        return resp

    def _extract_supplementary_assets(self, supp_assets, lecture_counter):
        _temp = []
        for entry in supp_assets:
            title = sanitize_filename(entry.get("title"))
            filename = entry.get("filename")
            download_urls = entry.get("download_urls")
            external_url = entry.get("external_url")
            asset_type = entry.get("asset_type").lower()
            id = entry.get("id")
            if asset_type == "file":
                if download_urls and isinstance(download_urls, dict):
                    extension = filename.rsplit(".", 1)[-1] if "." in filename else ""
                    download_url = download_urls.get("File", [])[0].get("file")
                    _temp.append(
                        {
                            "type": "file",
                            "title": title,
                            "filename": "{0:03d} ".format(lecture_counter) + filename,
                            "extension": extension,
                            "download_url": download_url,
                            "id": id,
                        }
                    )
            elif asset_type == "sourcecode":
                if download_urls and isinstance(download_urls, dict):
                    extension = filename.rsplit(".", 1)[-1] if "." in filename else ""
                    download_url = download_urls.get("SourceCode", [])[0].get("file")
                    _temp.append(
                        {
                            "type": "source_code",
                            "title": title,
                            "filename": "{0:03d} ".format(lecture_counter) + filename,
                            "extension": extension,
                            "download_url": download_url,
                            "id": id,
                        }
                    )
            elif asset_type == "externallink":
                _temp.append(
                    {
                        "type": "external_link",
                        "title": title,
                        "filename": "{0:03d} ".format(lecture_counter) + filename,
                        "extension": "txt",
                        "download_url": external_url,
                        "id": id,
                    }
                )
        return _temp

    def _extract_article(self, asset, id):
        return [
            {
                "type": "article",
                "body": asset.get("body"),
                "extension": "html",
                "id": id,
            }
        ]

    def _extract_ppt(self, asset, lecture_counter):
        _temp = []
        download_urls = asset.get("download_urls")
        filename = asset.get("filename")
        id = asset.get("id")
        if download_urls and isinstance(download_urls, dict):
            extension = filename.rsplit(".", 1)[-1] if "." in filename else ""
            download_url = download_urls.get("Presentation", [])[0].get("file")
            _temp.append(
                {
                    "type": "presentation",
                    "filename": "{0:03d} ".format(lecture_counter) + filename,
                    "extension": extension,
                    "download_url": download_url,
                    "id": id,
                }
            )
        return _temp

    def _extract_file(self, asset, lecture_counter):
        _temp = []
        download_urls = asset.get("download_urls")
        filename = asset.get("filename")
        id = asset.get("id")
        if download_urls and isinstance(download_urls, dict):
            extension = filename.rsplit(".", 1)[-1] if "." in filename else ""
            download_url = download_urls.get("File", [])[0].get("file")
            _temp.append(
                {
                    "type": "file",
                    "filename": "{0:03d} ".format(lecture_counter) + filename,
                    "extension": extension,
                    "download_url": download_url,
                    "id": id,
                }
            )
        return _temp

    def _extract_ebook(self, asset, lecture_counter):
        _temp = []
        download_urls = asset.get("download_urls")
        filename = asset.get("filename")
        id = asset.get("id")
        if download_urls and isinstance(download_urls, dict):
            extension = filename.rsplit(".", 1)[-1] if "." in filename else ""
            download_url = download_urls.get("E-Book", [])[0].get("file")
            _temp.append(
                {
                    "type": "ebook",
                    "filename": "{0:03d} ".format(lecture_counter) + filename,
                    "extension": extension,
                    "download_url": download_url,
                    "id": id,
                }
            )
        return _temp

    def _extract_audio(self, asset, lecture_counter):
        _temp = []
        download_urls = asset.get("download_urls")
        filename = asset.get("filename")
        id = asset.get("id")
        if download_urls and isinstance(download_urls, dict):
            extension = filename.rsplit(".", 1)[-1] if "." in filename else ""
            download_url = download_urls.get("Audio", [])[0].get("file")
            _temp.append(
                {
                    "type": "audio",
                    "filename": "{0:03d} ".format(lecture_counter) + filename,
                    "extension": extension,
                    "download_url": download_url,
                    "id": id,
                }
            )
        return _temp

    def _extract_sources(self, sources, skip_hls):
        _temp = []
        if sources and isinstance(sources, list):
            for source in sources:
                label = source.get("label")
                download_url = source.get("file")
                if not download_url:
                    continue
                if label.lower() == "audio":
                    continue
                height = label if label else None
                if height == "2160":
                    width = "3840"
                elif height == "1440":
                    width = "2560"
                elif height == "1080":
                    width = "1920"
                elif height == "720":
                    width = "1280"
                elif height == "480":
                    width = "854"
                elif height == "360":
                    width = "640"
                elif height == "240":
                    width = "426"
                else:
                    width = "256"
                if source.get("type") == "application/x-mpegURL" or "m3u8" in download_url:
                    if not skip_hls:
                        out = self._extract_m3u8(download_url)
                        if out:
                            _temp.extend(out)
                else:
                    _type = source.get("type")
                    _temp.append(
                        {
                            "type": "video",
                            "height": height,
                            "width": width,
                            "extension": _type.replace("video/", ""),
                            "download_url": download_url,
                        }
                    )
        return _temp

    def _extract_media_sources(self, sources):
        _temp = []
        if sources and isinstance(sources, list):
            for source in sources:
                _type = source.get("type")
                src = source.get("src")

                if _type == "application/dash+xml":
                    out = self._extract_mpd(src)
                    if out:
                        _temp.extend(out)
        return _temp

    def _extract_subtitles(self, tracks):
        _temp = []
        if tracks and isinstance(tracks, list):
            for track in tracks:
                if not isinstance(track, dict):
                    continue
                if track.get("_class") != "caption":
                    continue
                download_url = track.get("url")
                if not download_url or not isinstance(download_url, str):
                    continue
                lang = (
                    track.get("language")
                    or track.get("srclang")
                    or track.get("label")
                    or track["locale_id"].split("_")[0]
                )
                ext = "vtt" if "vtt" in download_url.rsplit(".", 1)[-1] else "srt"
                _temp.append(
                    {
                        "type": "subtitle",
                        "language": lang,
                        "extension": ext,
                        "download_url": download_url,
                    }
                )
        return _temp

    def _extract_m3u8(self, url):
        """extracts m3u8 streams"""
        asset_id_re = re.compile(r"assets/(?P<id>\d+)/")
        _temp = []

        # get temp folder
        temp_path = Path(Path.cwd(), "temp")

        # ensure the folder exists
        temp_path.mkdir(parents=True, exist_ok=True)

        # # extract the asset id from the url
        asset_id = asset_id_re.search(url).group("id")

        m3u8_path = Path(temp_path, f"index_{asset_id}.m3u8")

        try:
            try:
                r = self.session._get(url)
            except Exception as error:
                error_str = str(error)
                if (
                    "403" in error_str
                    or "ConnectionResetError" in error_str
                    or "Connection aborted" in error_str
                    or "10054" in error_str
                ):
                    try:
                        read_timeout = int(os.getenv("UDEMY_READ_TIMEOUT", "180"))
                    except ValueError:
                        read_timeout = 180
                    try:
                        connect_timeout = int(os.getenv("UDEMY_CONNECT_TIMEOUT", "30"))
                    except ValueError:
                        connect_timeout = 30

                    rr = _curl_cffi_get(url, dict(self.session._headers or {}), cj, (connect_timeout, read_timeout))
                    if rr is not None and getattr(rr, "status_code", None) == 200:
                        r = rr
                    else:
                        raise
                else:
                    raise
            _raise_for_status(r, url)
            raw_data = r.text

            # write to temp file for later
            with open(m3u8_path, "w") as f:
                f.write(r.text)

            m3u8_object = m3u8.loads(raw_data)
            playlists = m3u8_object.playlists
            seen = set()
            for pl in playlists:
                resolution = pl.stream_info.resolution
                codecs = pl.stream_info.codecs

                if not resolution:
                    continue
                if not codecs:
                    continue
                width, height = resolution

                if height in seen:
                    continue

                # we need to save the individual playlists to disk also
                playlist_path = Path(temp_path, f"index_{asset_id}_{width}x{height}.m3u8")

                with open(playlist_path, "w") as f:
                    try:
                        r = self.session._get(pl.uri)
                    except Exception as error:
                        error_str = str(error)
                        if (
                            "403" in error_str
                            or "ConnectionResetError" in error_str
                            or "Connection aborted" in error_str
                            or "10054" in error_str
                        ):
                            try:
                                read_timeout = int(os.getenv("UDEMY_READ_TIMEOUT", "180"))
                            except ValueError:
                                read_timeout = 180
                            try:
                                connect_timeout = int(os.getenv("UDEMY_CONNECT_TIMEOUT", "30"))
                            except ValueError:
                                connect_timeout = 30

                            rr = _curl_cffi_get(
                                pl.uri, dict(self.session._headers or {}), cj, (connect_timeout, read_timeout)
                            )
                            if rr is not None and getattr(rr, "status_code", None) == 200:
                                r = rr
                            else:
                                raise
                        else:
                            raise
                    _raise_for_status(r, pl.uri)
                    f.write(r.text)

                seen.add(height)
                _temp.append(
                    {
                        "type": "hls",
                        "height": height,
                        "width": width,
                        "extension": "mp4",
                        "download_url": playlist_path.as_uri(),
                    }
                )
        except Exception as error:
            logger.error(f"Udemy Says : '{error}' while fetching hls streams..")
        return _temp

    def _extract_mpd(self, url):
        """extracts mpd streams"""
        asset_id_re = re.compile(r"assets/(?P<id>\d+)/")
        _temp = {}

        # get temp folder
        temp_path = Path(Path.cwd(), "temp")

        # ensure the folder exists
        temp_path.mkdir(parents=True, exist_ok=True)

        # # extract the asset id from the url
        asset_id = asset_id_re.search(url).group("id")

        # download the mpd and save it to the temp file
        mpd_path = Path(temp_path, f"index_{asset_id}.mpd")

        try:
            if portal_name and course_name:
                self.session._headers.update(
                    {
                        "Referer": f"https://{portal_name}.udemy.com/course/{course_name}/learn/",
                        "Origin": f"https://{portal_name}.udemy.com",
                    }
                )
            with open(mpd_path, "wb") as f:
                try:
                    r = self.session._get(url)
                except Exception as exc:
                    exc_str = str(exc)
                    if "403" in exc_str and "index.mpd" in url and "token=" in url:
                        # Some portals reject signed asset requests when Authorization/cookies are attached.
                        # Retry with multiple strategies.
                        try:
                            try:
                                read_timeout = int(os.getenv("UDEMY_READ_TIMEOUT", "180"))
                            except ValueError:
                                read_timeout = 180
                            try:
                                connect_timeout = int(os.getenv("UDEMY_CONNECT_TIMEOUT", "30"))
                            except ValueError:
                                connect_timeout = 30

                            mpd_fetcher = os.getenv("UDEMY_MPD_FETCHER", "auto").strip().lower()
                            curl_on_403_env = os.getenv("UDEMY_MPD_CURL_CFFI_ON_403", "1").strip().lower()
                            curl_on_403 = curl_on_403_env not in ("0", "false", "no")

                            fallback_headers = {
                                k: v
                                for k, v in (self.session._headers or {}).items()
                                if k.lower() not in {"authorization", "x-udemy-authorization", "cookie"}
                            }

                            attempts = []

                            if cj is not None:
                                attempts.append(("no-auth-with-cookies", fallback_headers, cj))
                            attempts.append(("no-auth-no-cookies", fallback_headers, None))
                            attempts.append(("auth-no-cookies", dict(self.session._headers or {}), None))

                            forced_ok = False
                            if mpd_fetcher == "curl_cffi":
                                for _label, _headers, _cookies in attempts:
                                    rr0 = _curl_cffi_get(url, _headers, _cookies, (connect_timeout, read_timeout))
                                    if rr0 is not None and getattr(rr0, "status_code", None) == 200:
                                        logger.info("MPD fetched via curl_cffi (forced)")
                                        r = rr0
                                        forced_ok = True
                                        break

                            last_err = None
                            if not forced_ok:
                                for label, headers, cookies in attempts:
                                    logger.warning(
                                        "MPD 403 detected; retrying %s (timeout=(%s,%s))",
                                        label,
                                        connect_timeout,
                                        read_timeout,
                                    )
                                    try:
                                        rr = self.session._session.get(
                                            url,
                                            headers=headers,
                                            cookies=cookies,
                                            timeout=(connect_timeout, read_timeout),
                                        )
                                        if rr.status_code == 403:
                                            body_snippet = ""
                                            try:
                                                body_snippet = (rr.text or "")[:200].replace("\n", " ").replace("\r", " ")
                                            except Exception:
                                                body_snippet = ""
                                            logger.warning(
                                                "MPD retry %s returned 403. Response snippet: %s",
                                                label,
                                                body_snippet,
                                            )
                                            if curl_on_403 or "just a moment" in body_snippet.lower():
                                                rr2 = _curl_cffi_get(
                                                    url,
                                                    headers,
                                                    cookies,
                                                    (connect_timeout, read_timeout),
                                                )
                                                if rr2 is not None and getattr(rr2, "status_code", None) == 200:
                                                    logger.info("MPD Cloudflare challenge bypassed via curl_cffi")
                                                    r = rr2
                                                    break
                                        rr.raise_for_status()
                                        r = rr
                                        break
                                    except Exception as retry_exc:
                                        last_err = retry_exc
                                        continue
                                else:
                                    raise last_err or exc
                        except Exception:
                            raise exc
                f.write(r.content)

            ytdl = yt_dlp.YoutubeDL(
                {"quiet": True, "no_warnings": True, "allow_unplayable_formats": True, "enable_file_urls": True}
            )
            results = ytdl.extract_info(mpd_path.as_uri(), download=False, force_generic_extractor=True)
            formats = results.get("formats", [])
            best_audio = next(f for f in formats if (f["acodec"] != "none" and f["vcodec"] == "none"))
            # filter formats to remove any audio only formats
            formats = [f for f in formats if f["vcodec"] != "none" and f["acodec"] == "none"]
            if not best_audio:
                raise ValueError("No suitable audio format found in MPD")
            audio_format_id = best_audio.get("format_id")

            for format in formats:
                video_format_id = format.get("format_id")
                extension = format.get("ext")
                height = format.get("height")
                width = format.get("width")
                tbr = format.get("tbr", 0)

                # add to dict based on height
                if height not in _temp:
                    _temp[height] = []

                _temp[height].append(
                    {
                        "type": "dash",
                        "height": str(height),
                        "width": str(width),
                        "format_id": f"{video_format_id},{audio_format_id}",
                        "extension": extension,
                        "download_url": mpd_path.as_uri(),
                        "tbr": round(tbr),
                    }
                )
            # for each resolution, use only the highest bitrate
            _temp2 = []
            for height, formats in _temp.items():
                if formats:
                    # sort by tbr and take the first one
                    formats.sort(key=lambda x: x["tbr"], reverse=True)
                    _temp2.append(formats[0])
                else:
                    del _temp[height]

            _temp = _temp2
        except Exception:
            logger.exception(f"Error fetching MPD streams")

        # We don't delete the mpd file yet because we can use it to download later
        return _temp

    def extract_course_name(self, url):
        """
        @author r0oth3x49
        """
        obj = re.search(
            r"(?i)(?://(?P<portal_name>.+?).udemy.com/(?:course(/draft)*/)?(?P<name_or_id>[a-zA-Z0-9_-]+))",
            url,
        )
        if obj:
            return obj.group("portal_name"), obj.group("name_or_id")

    def extract_portal_name(self, url):
        obj = re.search(r"(?i)(?://(?P<portal_name>.+?).udemy.com)", url)
        if obj:
            return obj.group("portal_name")

    def _subscribed_courses(self, portal_name, course_name):
        results = []
        self.session._headers.update(
            {
                "Host": "{portal_name}.udemy.com".format(portal_name=portal_name),
                "Referer": "https://{portal_name}.udemy.com/home/my-courses/search/?q={course_name}".format(
                    portal_name=portal_name, course_name=course_name
                ),
            }
        )
        url = COURSE_SEARCH.format(
            portal_name=portal_name,
            course_name=course_name,
            page_size=os.getenv("UDEMY_COURSE_SEARCH_PAGE_SIZE", "100"),
        )
        try:
            webpage = self.session._get(url).content
            webpage = webpage.decode("utf8", "ignore")
            webpage = json.loads(webpage)
        except conn_error as error:
            logger.fatal(f"Connection error: {error}")
            time.sleep(0.8)
            sys.exit(1)
        except (ValueError, Exception) as error:
            err_str = str(error)
            if "403" in err_str:
                logger.warning("Subscribed course search returned 403; falling back to subscription-course flow")
                return []
            logger.fatal(f"{error} on {url}")
            time.sleep(0.8)
            sys.exit(1)
        else:
            results = webpage.get("results", [])
        return results

    def _extract_course_info_json(self, url, course_id):
        self.session._headers.update({"Referer": url})
        url = COURSE_URL.format(portal_name=portal_name, course_id=course_id)
        try:
            resp = self.session._get(url).json()
        except conn_error as error:
            logger.fatal(f"Connection error: {error}")
            time.sleep(0.8)
            sys.exit(1)
        else:
            return resp

    def _extract_course_curriculum(self, url, course_id, portal_name):
        self.session._headers.update({"Referer": url})
        url = CURRICULUM_ITEMS_URL.format(portal_name=portal_name, course_id=course_id)
        page = 1
        try:
            data = self.session._get(url, CURRICULUM_ITEMS_PARAMS).json()
        except conn_error as error:
            logger.fatal(f"Connection error: {error}")
            time.sleep(0.8)
            sys.exit(1)
        else:
            _next = data.get("next")
            _count = data.get("count")
            est_page_count = math.ceil(_count / 100)  # 100 is the max results per page
            while _next:
                logger.info(f"> Downloading course curriculum.. (Page {page + 1}/{est_page_count})")
                try:
                    resp = self.session._get(_next)
                    if not resp.ok:
                        logger.error(f"Failed to fetch a page, will retry")
                        continue
                    resp = resp.json()
                except conn_error as error:
                    logger.fatal(f"Connection error: {error}")
                    time.sleep(0.8)
                    sys.exit(1)
                else:
                    _next = resp.get("next")
                    results = resp.get("results")
                    if results and isinstance(results, list):
                        for d in resp["results"]:
                            data["results"].append(d)
                        page = page + 1
            return data

    def _extract_course(self, response, course_name):
        _temp = {}
        if response:
            for entry in response:
                course_id = str(entry.get("id"))
                published_title = entry.get("published_title")
                if course_name in (published_title, course_id):
                    _temp = entry
                    break
        return _temp

    def _my_courses(self, portal_name):
        results = []
        try:
            url = MY_COURSES_URL.format(portal_name=portal_name)
            webpage = self.session._get(url).json()
        except conn_error as error:
            logger.fatal(f"Connection error: {error}")
            time.sleep(0.8)
            sys.exit(1)
        except (ValueError, Exception) as error:
            logger.fatal(f"{error}")
            time.sleep(0.8)
            sys.exit(1)
        else:
            results = webpage.get("results", [])
        return results

    def _subscribed_collection_courses(self, portal_name):
        url = COLLECTION_URL.format(portal_name=portal_name)
        courses_lists = []
        try:
            webpage = self.session._get(url).json()
        except conn_error as error:
            logger.fatal(f"Connection error: {error}")
            time.sleep(0.8)
            sys.exit(1)
        except (ValueError, Exception) as error:
            logger.fatal(f"{error}")
            time.sleep(0.8)
            sys.exit(1)
        else:
            results = webpage.get("results", [])
            if results:
                [courses_lists.extend(courses.get("courses", [])) for courses in results if courses.get("courses", [])]
        return courses_lists

    def _archived_courses(self, portal_name):
        results = []
        try:
            url = MY_COURSES_URL.format(portal_name=portal_name)
            url = f"{url}&is_archived=true"
            webpage = self.session._get(url).json()
        except conn_error as error:
            logger.fatal(f"Connection error: {error}")
            time.sleep(0.8)
            sys.exit(1)
        except (ValueError, Exception) as error:
            logger.fatal(f"{error}")
            time.sleep(0.8)
            sys.exit(1)
        else:
            results = webpage.get("results", [])
        return results

    def _extract_subscription_course_info(self, url):
        url = (url or "").split("#", 1)[0]
        if portal_name:
            self.session._headers.update(
                {
                    "Host": f"{portal_name}.udemy.com",
                    "Origin": f"https://{portal_name}.udemy.com",
                    "Referer": f"https://{portal_name}.udemy.com/",
                }
            )

        try:
            try:
                read_timeout = int(os.getenv("UDEMY_READ_TIMEOUT", "180"))
            except ValueError:
                read_timeout = 180
            try:
                connect_timeout = int(os.getenv("UDEMY_CONNECT_TIMEOUT", "30"))
            except ValueError:
                connect_timeout = 30

            course_html = self.session._get(url).text
        except Exception as exc:
            exc_str = str(exc)
            if "403" in exc_str:
                fallback_no_auth_headers = {
                    k: v
                    for k, v in (self.session._headers or {}).items()
                    if k.lower() not in {"authorization", "x-udemy-authorization", "cookie"}
                }
                if portal_name:
                    fallback_no_auth_headers.update(
                        {
                            "Host": f"{portal_name}.udemy.com",
                            "Origin": f"https://{portal_name}.udemy.com",
                            "Referer": f"https://{portal_name}.udemy.com/",
                        }
                    )

                attempts = [
                    ("auth-with-cookies", dict(self.session._headers or {}), cj),
                    ("no-auth-with-cookies", fallback_no_auth_headers, cj),
                    ("auth-no-cookies", dict(self.session._headers or {}), None),
                    ("no-auth-no-cookies", fallback_no_auth_headers, None),
                ]

                last_err = exc
                for label, headers, cookies in attempts:
                    logger.warning(
                        "Course page 403 detected; retrying %s (timeout=(%s,%s))",
                        label,
                        connect_timeout,
                        read_timeout,
                    )
                    try:
                        rr = self.session._session.get(
                            url,
                            headers=headers,
                            cookies=cookies,
                            timeout=(connect_timeout, read_timeout),
                        )
                        if rr.status_code == 403:
                            body_snippet = ""
                            try:
                                body_snippet = (rr.text or "")[:200].replace("\n", " ").replace("\r", " ")
                            except Exception:
                                body_snippet = ""
                            logger.warning(
                                "Course page retry %s returned 403. Response snippet: %s",
                                label,
                                body_snippet,
                            )
                        rr.raise_for_status()
                        course_html = rr.text
                        break
                    except Exception as retry_exc:
                        last_err = retry_exc
                        continue
                else:
                    raise last_err
            else:
                raise
        soup = BeautifulSoup(course_html, "lxml")
        data = soup.find("div", {"class": "ud-component--course-taking--app"})
        if not data:
            logger.fatal(
                "Could not find course data. Possible causes are: Missing cookies.txt file, incorrect url (should end with /learn), not logged in to udemy in specified browser."
            )
            self.session.terminate()
            sys.exit(1)
        data_args = data.attrs["data-module-args"]
        data_json = json.loads(data_args)
        course_id = data_json.get("courseId", None)
        return course_id

    def _extract_course_info(self, url):
        global portal_name
        portal_name, course_name = self.extract_course_name(url)
        course = {"portal_name": portal_name}

        if not is_subscription_course:
            results = self._subscribed_courses(portal_name=portal_name, course_name=course_name)
            course = self._extract_course(response=results, course_name=course_name)
            if not course:
                results = self._my_courses(portal_name=portal_name)
                course = self._extract_course(response=results, course_name=course_name)
            if not course:
                results = self._subscribed_collection_courses(portal_name=portal_name)
                course = self._extract_course(response=results, course_name=course_name)
            if not course:
                results = self._archived_courses(portal_name=portal_name)
                course = self._extract_course(response=results, course_name=course_name)

        if not course or is_subscription_course:
            course_id = self._extract_subscription_course_info(url)
            course = self._extract_course_info_json(url, course_id)

        if course:
            return course.get("id"), course
        if not course:
            logger.fatal("Downloading course information, course id not found .. ")
            logger.fatal(
                "It seems either you are not enrolled or you have to visit the course atleast once while you are logged in.",
            )
            logger.info(
                "Terminating Session...",
            )
            self.session.terminate()
            logger.info(
                "Session terminated.",
            )
            sys.exit(1)

    def _parse_lecture(self, lecture: dict):
        retVal = []

        index = lecture.get("index")  # this is lecture_counter
        lecture_data = lecture.get("data")
        asset = lecture_data.get("asset")
        supp_assets = lecture_data.get("supplementary_assets")

        if isinstance(asset, dict):
            asset_type = asset.get("asset_type").lower() or asset.get("assetType").lower()
            if asset_type == "article":
                retVal.extend(self._extract_article(asset, index))
            elif asset_type == "video":
                pass
            elif asset_type == "e-book":
                retVal.extend(self._extract_ebook(asset, index))
            elif asset_type == "file":
                retVal.extend(self._extract_file(asset, index))
            elif asset_type == "presentation":
                retVal.extend(self._extract_ppt(asset, index))
            elif asset_type == "audio":
                retVal.extend(self._extract_audio(asset, index))
            else:
                logger.warning(f"Unknown asset type: {asset_type}")

            if isinstance(supp_assets, list) and len(supp_assets) > 0:
                retVal.extend(self._extract_supplementary_assets(supp_assets, index))

        if asset != None:
            stream_urls = asset.get("stream_urls")
            if stream_urls != None:
                # not encrypted
                if stream_urls and isinstance(stream_urls, dict):
                    sources = stream_urls.get("Video")
                    tracks = asset.get("captions")
                    # duration = asset.get("time_estimation")
                    sources = self._extract_sources(sources, skip_hls)
                    subtitles = self._extract_subtitles(tracks)
                    sources_count = len(sources)
                    subtitle_count = len(subtitles)
                    lecture.pop("data")  # remove the raw data object after processing
                    lecture = {
                        **lecture,
                        "assets": retVal,
                        "assets_count": len(retVal),
                        "sources": sources,
                        "subtitles": subtitles,
                        "subtitle_count": subtitle_count,
                        "sources_count": sources_count,
                        "is_encrypted": False,
                        "asset_id": asset.get("id"),
                        "type": asset.get("asset_type"),
                    }
                else:
                    lecture.pop("data")  # remove the raw data object after processing
                    lecture = {
                        **lecture,
                        "html_content": asset.get("body"),
                        "extension": "html",
                        "assets": retVal,
                        "assets_count": len(retVal),
                        "subtitle_count": 0,
                        "sources_count": 0,
                        "is_encrypted": False,
                        "asset_id": asset.get("id"),
                        "type": asset.get("asset_type"),
                    }
            else:
                # encrypted
                media_sources = asset.get("media_sources")
                if media_sources and isinstance(media_sources, list):
                    sources = self._extract_media_sources(media_sources)
                    tracks = asset.get("captions")
                    # duration = asset.get("time_estimation")
                    subtitles = self._extract_subtitles(tracks)
                    sources_count = len(sources)
                    subtitle_count = len(subtitles)
                    lecture.pop("data")  # remove the raw data object after processing
                    lecture = {
                        **lecture,
                        # "duration": duration,
                        "assets": retVal,
                        "assets_count": len(retVal),
                        "video_sources": sources,
                        "subtitles": subtitles,
                        "subtitle_count": subtitle_count,
                        "sources_count": sources_count,
                        "is_encrypted": True,
                        "asset_id": asset.get("id"),
                        "type": asset.get("asset_type"),
                    }

                else:
                    lecture.pop("data")  # remove the raw data object after processing
                    lecture = {
                        **lecture,
                        "html_content": asset.get("body"),
                        "extension": "html",
                        "assets": retVal,
                        "assets_count": len(retVal),
                        "subtitle_count": 0,
                        "sources_count": 0,
                        "is_encrypted": False,
                        "asset_id": asset.get("id"),
                        "type": asset.get("asset_type"),
                    }
        else:
            lecture = {
                **lecture,
                "assets": retVal,
                "assets_count": len(retVal),
                "asset_id": lecture_data.get("id"),
                "type": lecture_data.get("type"),
            }

        return lecture


class Session(object):
    def __init__(self):
        self._headers = HEADERS
        self._session = requests.sessions.Session()
        if DISABLE_PROXY:
            self._session.trust_env = False
        self._session.mount(
            "https://",
            SSLCiphers(
                cipher_list="ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-SHA384:ECDHE-ECDSA-AES256-SHA384:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-SHA256:AES256-SH"
            ),
        )

    def _set_auth_headers(self, bearer_token=""):
        self._headers["Authorization"] = "Bearer {}".format(bearer_token)
        self._headers["X-Udemy-Authorization"] = "Bearer {}".format(bearer_token)

    def _get(self, url, params=None):
        last_response = None
        last_exc = None
        try:
            max_retries = int(os.getenv("UDEMY_MAX_RETRIES", "10"))
        except ValueError:
            max_retries = 10
        try:
            read_timeout = int(os.getenv("UDEMY_READ_TIMEOUT", "180"))
        except ValueError:
            read_timeout = 180
        try:
            connect_timeout = int(os.getenv("UDEMY_CONNECT_TIMEOUT", "30"))
        except ValueError:
            connect_timeout = 30
        try:
            backoff_max = float(os.getenv("UDEMY_RETRY_BACKOFF_MAX", "30"))
        except ValueError:
            backoff_max = 30.0
        for i in range(max_retries):
            try:
                session = self._session.get(
                    url,
                    headers=self._headers,
                    cookies=cj,
                    params=params,
                    timeout=(connect_timeout, read_timeout),
                )
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                logger.error("Failed request " + url)
                logger.error(
                    f"{exc} (timeout=({connect_timeout},{read_timeout})), retrying (attempt {i} )..."
                )
                time.sleep(min(backoff_max, 1.0 * (2**i)))
                continue
            if session.ok:
                return session
            if session.status_code in [502, 503, 504]:
                last_response = session
                logger.error("Failed request " + url)
                logger.error(
                    f"{session.status_code} {session.reason} (timeout=({connect_timeout},{read_timeout})), retrying (attempt {i} )..."
                )
                time.sleep(min(backoff_max, 1.0 * (2**i)))
                continue
            if session.status_code == 429:
                last_response = session
                retry_after = session.headers.get("Retry-After")
                try:
                    wait = int(retry_after) if retry_after else 0
                except ValueError:
                    wait = 0
                if wait <= 0:
                    wait = min(30, 2 * (i + 1))
                logger.error("Failed request " + url)
                logger.error(
                    f"{session.status_code} {session.reason} (timeout=({connect_timeout},{read_timeout})), retrying (attempt {i} )..."
                )
                time.sleep(wait)
                continue
            if session.status_code == 403:
                raise Exception(f"Failed request {url} ({session.status_code} {session.reason})")
            last_response = session
            logger.error("Failed request " + url)
            logger.error(
                f"{session.status_code} {session.reason} (timeout=({connect_timeout},{read_timeout})), retrying (attempt {i} )..."
            )
            time.sleep(min(backoff_max, 1.0 * (2**i)))

        if last_response is not None:
            raise Exception(
                f"Failed request {url} after {max_retries} attempts ({last_response.status_code} {last_response.reason})"
            )
        if last_exc is not None:
            raise Exception(f"Failed request {url} after {max_retries} attempts ({last_exc})")
        raise Exception(f"Failed request {url}: no response received")

    def _post(self, url, data, redirect=True):
        session = self._session.post(url, data, headers=self._headers, allow_redirects=redirect, cookies=cj)
        if session.ok:
            return session
        if not session.ok:
            raise Exception(f"{session.status_code} {session.reason}")

    def terminate(self):
        self._set_auth_headers()
        return


class UdemyAuth(object):
    def __init__(self, username="", password="", cache_session=False):
        self.username = username
        self.password = password
        self._cache = cache_session
        self._session = Session()

    def authenticate(self, bearer_token=None):
        if bearer_token:
            self._session._set_auth_headers(bearer_token=bearer_token)
            return self._session
        else:
            return None


def durationtoseconds(period):
    """
    @author Jayapraveen
    """

    # Duration format in PTxDxHxMxS
    if period[:2] == "PT":
        period = period[2:]
        day = int(period.split("D")[0] if "D" in period else 0)
        hour = int(period.split("H")[0].split("D")[-1] if "H" in period else 0)
        minute = int(period.split("M")[0].split("H")[-1] if "M" in period else 0)
        second = period.split("S")[0].split("M")[-1]
        # logger.debug("Total time: " + str(day) + " days " + str(hour) + " hours " +
        #       str(minute) + " minutes and " + str(second) + " seconds")
        total_time = float(
            str((day * 24 * 60 * 60) + (hour * 60 * 60) + (minute * 60) + (int(second.split(".")[0])))
            + "."
            + str(int(second.split(".")[-1]))
        )
        return total_time

    else:
        logger.error("Duration Format Error")
        return None


def mux_process(
    video_in: str,
    audio_in: str,
    video_title: str,
    output_path: str,
    audio_key: str,
    video_key: str,
    audio_kid: Optional[str] = None,
    video_kid: Optional[str] = None,
) -> int:
    try:
        output_target = Path(output_path)
        workdir = output_target.parent

        video_input_path = Path(video_in)
        audio_input_path = Path(audio_in)
        if not video_input_path.is_absolute():
            video_input_path = workdir / video_input_path
        if not audio_input_path.is_absolute():
            audio_input_path = workdir / audio_input_path

        resolved_video_kid = video_kid or extract_kid(str(video_input_path))
        resolved_audio_kid = audio_kid or extract_kid(str(audio_input_path))
        if not resolved_video_kid or not resolved_audio_kid:
            logger.error("Could not extract KID(s) for DRM lecture: %s", video_title)
            return 1

        # Shaka Packager stream descriptors use comma-separated fields.
        # Avoid putting full output paths (which may contain commas) into the descriptor.
        dec_stem = output_target.with_suffix("").name
        video_dec_name = f"{dec_stem}.video.dec.mp4"
        audio_dec_name = f"{dec_stem}.audio.dec.mp4"

        packager_cmd = [
            "shaka-packager",
            f"in={video_input_path.name},stream=video,output={video_dec_name},drm_label=VIDEO",
            f"in={audio_input_path.name},stream=audio,output={audio_dec_name},drm_label=AUDIO",
            "--enable_raw_key_decryption",
            "--keys",
            f"label=VIDEO:key_id={resolved_video_kid}:key={video_key},label=AUDIO:key_id={resolved_audio_kid}:key={audio_key}",
        ]
        packager = subprocess.run(packager_cmd, capture_output=True, text=True, cwd=str(workdir))
        if packager.returncode != 0:
            logger.error("> shaka-packager failed (code=%s) for lecture: %s", packager.returncode, video_title)
            if packager.stdout:
                logger.error("> shaka-packager stdout: %s", packager.stdout.strip())
            if packager.stderr:
                logger.error("> shaka-packager stderr: %s", packager.stderr.strip())
            return packager.returncode

        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            video_dec_name,
            "-i",
            audio_dec_name,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            output_path,
        ]
        ffmpeg = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, cwd=str(workdir))
        if ffmpeg.returncode != 0:
            logger.error("> ffmpeg merge failed (code=%s) for lecture: %s", ffmpeg.returncode, video_title)
            if ffmpeg.stdout:
                logger.error("> ffmpeg stdout: %s", ffmpeg.stdout.strip())
            if ffmpeg.stderr:
                logger.error("> ffmpeg stderr: %s", ffmpeg.stderr.strip())
        return ffmpeg.returncode
    except Exception:
        logger.exception("Muxing pipeline failed for lecture: %s", video_title)
        return 1
    finally:
        try:
            output_target = Path(output_path)
            workdir = output_target.parent
            dec_stem = output_target.with_suffix("").name
            video_dec = workdir / f"{dec_stem}.video.dec.mp4"
            audio_dec = workdir / f"{dec_stem}.audio.dec.mp4"
            if video_dec.exists():
                os.remove(str(video_dec))
            if audio_dec.exists():
                os.remove(str(audio_dec))
        except Exception:
            pass


def handle_segments(url, format_id, lecture_id, video_title, output_path, chapter_dir):
    os.chdir(os.path.join(chapter_dir))

    video_filepath_enc = lecture_id + ".encrypted.mp4"
    audio_filepath_enc = lecture_id + ".encrypted.m4a"
    temp_output_path = os.path.join(chapter_dir, lecture_id + ".mp4")

    logger.info("> Downloading Lecture Tracks...")

    def _sanitize_url_for_log(u: str) -> str:
        try:
            from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

            parts = urlsplit(u)
            q = parse_qsl(parts.query, keep_blank_values=True)
            if not q:
                return u
            redacted_keys = {
                "token",
                "signature",
                "policy",
                "key-pair-id",
                "x-amz-signature",
                "x-amz-credential",
                "x-amz-security-token",
            }
            nq = []
            for k, v in q:
                if k.lower() in redacted_keys:
                    nq.append((k, "***"))
                else:
                    nq.append((k, v))
            new_query = urlencode(nq)
            return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))
        except Exception:
            return u

    base_args = [
        YTDLP_PATH,
        "--enable-file-urls",
        "--force-generic-extractor",
        "--allow-unplayable-formats",
        "--retries",
        "10",
        "--fragment-retries",
        "10",
        "--file-access-retries",
        "10",
        "--fixup",
        "never",
        "-k",
        "-o",
        f"{lecture_id}.encrypted.%(ext)s",
        "-f",
        format_id,
        f"{url}",
    ]

    def _run_ytdlp(cmd_args):
        result = subprocess.run(cmd_args, capture_output=True, text=True)
        return result.returncode, (result.stdout or ""), (result.stderr or "")

    aria2_args = [
        YTDLP_PATH,
        "--enable-file-urls",
        "--force-generic-extractor",
        "--allow-unplayable-formats",
        "--retries",
        "10",
        "--fragment-retries",
        "10",
        "--file-access-retries",
        "10",
        "--concurrent-fragments",
        f"{concurrent_downloads}",
        "--downloader",
        "aria2c",
        "--downloader-args",
        ARIA2C_DOWNLOADER_ARGS,
        "--fixup",
        "never",
        "-k",
        "-o",
        f"{lecture_id}.encrypted.%(ext)s",
        "-f",
        format_id,
        f"{url}",
    ]

    download_method = "aria2c"
    start_download = time.time()
    try:
        safe_args = list(aria2_args)
        safe_args[-1] = _sanitize_url_for_log(url)
        logger.info("> DRM yt-dlp args (%s, concurrent_fragments=%s): %s", download_method, concurrent_downloads, safe_args)
    except Exception:
        pass
    ret_code, out, err = _run_ytdlp(aria2_args)
    logger.info("> Lecture track download finished in %.2fs (method=%s, code=%s)", time.time() - start_download, download_method, ret_code)
    if ret_code != 0:
        logger.warning("Return code from downloader was non-0 (code=%s). Will retry without aria2c.", ret_code)
        if out.strip():
            logger.error("> yt-dlp stdout (truncated): %s", out.strip()[-4000:])
        if err.strip():
            logger.error("> yt-dlp stderr (truncated): %s", err.strip()[-4000:])

        fallback_args = [
            YTDLP_PATH,
            "--enable-file-urls",
            "--force-generic-extractor",
            "--allow-unplayable-formats",
            "--retries",
            "10",
            "--fragment-retries",
            "10",
            "--file-access-retries",
            "10",
            "--concurrent-fragments",
            "1",
            "--fixup",
            "never",
            "-k",
            "-o",
            f"{lecture_id}.encrypted.%(ext)s",
            "-f",
            format_id,
            f"{url}",
        ]
        download_method = "native"
        start_download = time.time()
        try:
            safe_args = list(fallback_args)
            safe_args[-1] = _sanitize_url_for_log(url)
            logger.info("> DRM yt-dlp args (%s, concurrent_fragments=1): %s", download_method, safe_args)
        except Exception:
            pass
        ret_code, out, err = _run_ytdlp(fallback_args)
        logger.info("> Lecture track download finished in %.2fs (method=%s, code=%s)", time.time() - start_download, download_method, ret_code)
        if ret_code != 0:
            logger.warning("Fallback download (no aria2c) also failed (code=%s), skipping!", ret_code)
            if out.strip():
                logger.error("> yt-dlp stdout (truncated): %s", out.strip()[-4000:])
            if err.strip():
                logger.error("> yt-dlp stderr (truncated): %s", err.strip()[-4000:])
            record_strict_failure(lecture_id, video_title, f"yt-dlp download failed (code={ret_code})")
            return False

    logger.info("> Lecture Tracks Downloaded")

    audio_kid = None
    video_kid = None

    try:
        video_kid = extract_kid(video_filepath_enc)
        logger.info("KID for video file is: " + video_kid)
    except Exception:
        logger.exception(f"Error extracting video kid")
        record_strict_failure(lecture_id, video_title, "failed to extract video KID")
        return False

    try:
        audio_kid = extract_kid(audio_filepath_enc)
        logger.info("KID for audio file is: " + audio_kid)
    except Exception:
        logger.exception(f"Error extracting audio kid")
        record_strict_failure(lecture_id, video_title, "failed to extract audio KID")
        return False

    audio_key = None
    video_key = None

    if audio_kid is not None:
        try:
            audio_key = keys[audio_kid]
        except KeyError:
            logger.error(
                f"Audio key not found for {audio_kid}, if you have the key then you probably didn't add them to the key file correctly."
            )
            record_strict_failure(lecture_id, video_title, f"audio key not found for KID {audio_kid}")
            return False

    if video_kid is not None:
        try:
            video_key = keys[video_kid]
        except KeyError:
            logger.error(
                f"Video key not found for {audio_kid}, if you have the key then you probably didn't add them to the key file correctly."
            )
            record_strict_failure(lecture_id, video_title, f"video key not found for KID {video_kid}")
            return False

    try:
        # logger.info("> Decrypting video, this might take a minute...")
        # ret_code = decrypt(video_kid, video_filepath_enc, video_filepath_dec)
        # if ret_code != 0:
        #     logger.error("> Return code from the decrypter was non-0 (error), skipping!")
        #     return
        # logger.info("> Decryption complete")
        # logger.info("> Decrypting audio, this might take a minute...")
        # decrypt(audio_kid, audio_filepath_enc, audio_filepath_dec)
        # if ret_code != 0:
        #     logger.error("> Return code from the decrypter was non-0 (error), skipping!")
        #     return
        # logger.info("> Decryption complete")
        logger.info("> Merging video and audio, this might take a minute...")
        ret_code = mux_process(
            video_filepath_enc,
            audio_filepath_enc,
            video_title,
            temp_output_path,
            audio_key,
            video_key,
            audio_kid,
            video_kid,
        )
        if ret_code != 0:
            logger.error("> DRM muxing pipeline returned non-0 (code=%s), skipping!", ret_code)
            record_strict_failure(lecture_id, video_title, f"mux/merge failed (code={ret_code})")
            return False
        logger.info("> Merging complete, renaming final file...")
        os.rename(temp_output_path, output_path)
        logger.info("> Cleaning up temporary files...")
        os.remove(video_filepath_enc)
        os.remove(audio_filepath_enc)
    except Exception as e:
        logger.exception(f"Muxing error: {e}")
        record_strict_failure(lecture_id, video_title, f"muxing exception: {e}")
        return False
    finally:
        os.chdir(HOME_DIR)
        # if the url is a file url, we need to remove the file after we're done with it
        if url.startswith("file://"):
            try:
                os.unlink(url[7:])
            except:
                pass
    return True


def check_for_aria():
    try:
        subprocess.Popen(["aria2c", "-v"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait()
        return True
    except FileNotFoundError:
        return False
    except Exception:
        logger.exception(
            "> Unexpected exception while checking for Aria2c, please tell the program author about this! "
        )
        return True


def check_for_ffmpeg():
    try:
        subprocess.Popen(["ffmpeg"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL).wait()
        return True
    except FileNotFoundError:
        return False
    except Exception:
        logger.exception(
            "> Unexpected exception while checking for FFMPEG, please tell the program author about this! "
        )
        return True


def check_for_shaka():
    try:
        subprocess.Popen(["shaka-packager", "-version"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL).wait()
        return True
    except FileNotFoundError:
        return False
    except Exception:
        logger.exception(
            "> Unexpected exception while checking for shaka-packager, please tell the program author about this! "
        )
        return True


def find_yt_dlp_path():
    python_dir = os.path.dirname(sys.executable)
    candidate = os.path.join(python_dir, "yt-dlp.exe" if os.name == "nt" else "yt-dlp")
    if os.path.isfile(candidate):
        return os.path.abspath(candidate)
    for executable in ("yt-dlp", "yt-dlp.exe"):
        path = shutil.which(executable)
        if path:
            return path
    return None


def check_for_yt_dlp():
    global YTDLP_PATH
    try:
        path = find_yt_dlp_path()
        if path:
            YTDLP_PATH = path
            return True
        return False
    except Exception:
        logger.exception(
            "> Unexpected exception while checking for yt-dlp, please tell the program author about this! "
        )
        return True


def download(url, path, filename):
    """
    @author Puyodead1
    """
    file_size = int(requests.head(url).headers["Content-Length"])
    if os.path.exists(path):
        first_byte = os.path.getsize(path)
    else:
        first_byte = 0
    if first_byte >= file_size:
        return file_size
    header = {"Range": "bytes=%s-%s" % (first_byte, file_size)}
    pbar = tqdm(total=file_size, initial=first_byte, unit="B", unit_scale=True, desc=filename)
    res = requests.get(url, headers=header, stream=True)
    res.raise_for_status()
    with open(path, encoding="utf8", mode="ab") as f:
        for chunk in res.iter_content(chunk_size=1024):
            if chunk:
                f.write(chunk)
                pbar.update(1024)
    pbar.close()
    return file_size


def download_aria(url, file_dir, filename):
    """
    @author Puyodead1
    """
    def _sanitize_url_for_log(u: str) -> str:
        try:
            from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

            parts = urlsplit(u)
            q = parse_qsl(parts.query, keep_blank_values=True)
            if not q:
                return u
            redacted_keys = {
                "token",
                "signature",
                "policy",
                "key-pair-id",
                "x-amz-signature",
                "x-amz-credential",
                "x-amz-security-token",
            }
            nq = []
            for k, v in q:
                if k.lower() in redacted_keys:
                    nq.append((k, "***"))
                else:
                    nq.append((k, v))
            new_query = urlencode(nq)
            return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))
        except Exception:
            return u

    args = [
        "aria2c",
        url,
        "-o",
        filename,
        "-d",
        file_dir,
        "-j16",
        "-s20",
        "-x16",
        "-c",
        "--auto-file-renaming=false",
        "--summary-interval=0",
        "--disable-ipv6",
        "--follow-torrent=false",
    ]

    try:
        safe_args = list(args)
        safe_args[1] = _sanitize_url_for_log(url)
        logger.info("aria2c args: %s", safe_args)
    except Exception:
        pass
    process = subprocess.Popen(args)
    log_subprocess_output("ARIA2-STDOUT", process.stdout)
    log_subprocess_output("ARIA2-STDERR", process.stderr)
    ret_code = process.wait()
    if ret_code != 0:
        raise Exception("Return code from the downloader was non-0 (error)")
    return ret_code


def process_caption(caption, lecture_title, lecture_dir):
    global translator, auto_translate
    
    filename = f"%s_%s.%s" % (sanitize_filename(lecture_title), caption.get("language"), caption.get("extension"))
    filename_no_ext = f"%s_%s" % (sanitize_filename(lecture_title), caption.get("language"))
    filepath = os.path.join(lecture_dir, filename)

    if os.path.isfile(filepath):
        logger.info("    > Caption '%s' already downloaded." % filename)
    else:
        logger.info(f"    >  Downloading caption: '%s'" % filename)
        try:
            ret_code = download_aria(caption.get("download_url"), lecture_dir, filename)
            logger.debug(f"      > Download return code: {ret_code}")
        except Exception as e:
            if tries >= 3:
                logger.error(f"    > Error downloading caption: {e}. Exceeded retries, skipping.")
                return
            else:
                logger.error(f"    > Error downloading caption: {e}. Will retry {3-tries} more times.")
                process_caption(caption, lecture_title, lecture_dir, tries + 1)
        if caption.get("extension") == "vtt":
            try:
                logger.info("    > Converting caption to SRT format...")
                convert(lecture_dir, filename_no_ext)
                logger.info("    > Caption conversion complete.")
                if not keep_vtt:
                    os.remove(filepath)
            except Exception:
                logger.exception(f"    > Error converting caption")
    
    # Auto-translate English captions to Chinese if enabled
    if auto_translate and translator and caption.get("language") == "en":
        srt_filepath = os.path.join(lecture_dir, filename_no_ext + ".srt")
        dual_srt_path = os.path.join(lecture_dir, f"{sanitize_filename(lecture_title)}_en_zh.srt")
        if os.path.isfile(dual_srt_path):
            logger.info(
                "    > Dual-language subtitle already exists (%s), skipping translation.",
                os.path.basename(dual_srt_path),
            )
            if os.path.isfile(srt_filepath):
                try:
                    os.remove(srt_filepath)
                    logger.info("    > Removed redundant English subtitle after skipping translation.")
                except OSError as err:
                    logger.warning("    > Could not remove redundant English subtitle: %s", err)
        elif os.path.isfile(srt_filepath):
            try:
                import pysrt
                logger.info("    > Translating caption to Chinese...")

                def _translate_and_save(src_path: str, out_path: str, lecture_name: str):
                    start_time = time.time()

                    # Load English SRT
                    subs = pysrt.open(src_path, encoding='utf-8')

                    # Extract all text for translation
                    texts = [sub.text for sub in subs]

                    # Translate all texts
                    translated_texts = translator.translate_batch(
                        texts,
                        source_lang="EN",
                        target_lang="ZH",
                        max_retries=3,
                    )

                    # Create dual-language version (EN + ZH)
                    dual_subs = pysrt.SubRipFile()
                    for idx, (sub, zh_text) in enumerate(zip(subs, translated_texts)):
                        if zh_text:
                            # Combine English and Chinese
                            dual_text = f"{sub.text}\n{zh_text}"
                        else:
                            # If translation failed, keep English only
                            dual_text = sub.text
                            logger.warning(f"    > Translation failed for subtitle {idx + 1}, keeping English only")

                        dual_sub = pysrt.SubRipItem(
                            index=sub.index,
                            start=sub.start,
                            end=sub.end,
                            text=dual_text
                        )
                        dual_subs.append(dual_sub)

                    # Save dual-language SRT
                    dual_subs.save(out_path, encoding='utf-8')
                    logger.info(f"    > Dual-language subtitle saved: {os.path.basename(out_path)}")

                    # Remove standalone English caption to keep only the bilingual file
                    try:
                        os.remove(src_path)
                        logger.info("    > Removed original English subtitle (kept EN+ZH file only)")
                    except OSError as err:
                        logger.warning(f"    > Could not remove English subtitle: {err}")

                    duration = time.time() - start_time
                    logger.info(
                        "    > Translation finished in %.2fs (%s)",
                        duration,
                        os.path.basename(out_path),
                    )
                    return lecture_name

                async_env = os.getenv("TRANSLATE_ASYNC", "1").strip().lower()
                async_enabled = async_env not in ("0", "false", "no")

                if async_enabled:
                    _ensure_translation_executor()
                    future = translation_executor.submit(
                        _translate_and_save,
                        srt_filepath,
                        dual_srt_path,
                        lecture_title,
                    )
                    with translation_lock:
                        translation_futures.append(future)
                    logger.info(
                        "    > Translation task submitted (%s)",
                        os.path.basename(srt_filepath),
                    )
                else:
                    _translate_and_save(srt_filepath, dual_srt_path, lecture_title)
                
            except Exception as e:
                logger.exception(f"    > Error during translation: {e}")


def _ensure_translation_executor():
    global translation_executor
    if translation_executor is not None:
        return
    workers_env = os.getenv("SUBTITLE_TRANSLATE_FILE_MAX_WORKERS") or os.getenv("TRANSLATE_FILE_MAX_WORKERS")
    try:
        workers = max(1, int(workers_env)) if workers_env else 1
    except ValueError:
        workers = 1
    translation_executor = ThreadPoolExecutor(max_workers=workers)
    logger.info("    > Translation executor started (workers=%d)", workers)


def wait_for_translation_tasks():
    global translation_executor, translation_futures
    if translation_executor is None:
        return

    with translation_lock:
        futures = list(translation_futures)
        translation_futures = []

    if not futures:
        translation_executor.shutdown(wait=True)
        translation_executor = None
        return

    logger.info("> Waiting for %d translation task(s) to finish...", len(futures))
    start = time.time()
    completed = 0
    for future in as_completed(futures):
        completed += 1
        try:
            lecture = future.result()
            logger.info("> Translation task %d/%d completed (%s)", completed, len(futures), lecture)
        except Exception as exc:
            logger.error("> Translation task %d/%d failed: %s", completed, len(futures), exc)

    duration = time.time() - start
    logger.info("> All translation tasks completed in %.2fs", duration)
    translation_executor.shutdown(wait=True)
    translation_executor = None


def process_lecture(lecture, lecture_path, chapter_dir):
    lecture_id = lecture.get("id")
    lecture_title = lecture.get("lecture_title")
    is_encrypted = lecture.get("is_encrypted")
    lecture_sources = lecture.get("video_sources")

    if is_encrypted:
        if len(lecture_sources) > 0:
            source = lecture_sources[-1]  # last index is the best quality
            if isinstance(quality, int):
                source = min(lecture_sources, key=lambda x: abs(int(x.get("height")) - quality))
            logger.info(
                f"      > Lecture '{lecture_title}' has DRM, attempting to download. Selected quality: {source.get('height')}"
            )
            ok = handle_segments(
                source.get("download_url"),
                source.get("format_id"),
                str(lecture_id),
                lecture_title,
                lecture_path,
                chapter_dir,
            )
            if ok is False:
                record_strict_failure(str(lecture_id), lecture_title, "DRM handler failed")
        else:
            logger.info(f"      > Lecture '{lecture_title}' is missing media links")
            logger.debug(f"Lecture source count: {len(lecture_sources)}")
            record_strict_failure(str(lecture_id), lecture_title, "missing media links")
    else:
        sources = lecture.get("sources")
        sources = sorted(sources, key=lambda x: int(x.get("height")), reverse=True)
        if sources:
            if not os.path.isfile(lecture_path):
                logger.info("      > Lecture doesn't have DRM, attempting to download...")
                source = sources[0]  # first index is the best quality
                if isinstance(quality, int):
                    source = min(sources, key=lambda x: abs(int(x.get("height")) - quality))
                try:
                    logger.info("      ====== Selected quality: %s %s", source.get("type"), source.get("height"))
                    url = source.get("download_url")
                    source_type = source.get("type")
                    if source_type == "hls":
                        temp_filepath = lecture_path.replace(".mp4", ".%(ext)s")
                        cmd = [
                            YTDLP_PATH,
                            "--enable-file-urls",
                            "--force-generic-extractor",
                            "--allow-unplayable-formats",
                            "--retries",
                            "10",
                            "--fragment-retries",
                            "10",
                            "--file-access-retries",
                            "10",
                            "--concurrent-fragments",
                            f"{concurrent_downloads}",
                            "--downloader",
                            "aria2c",
                            "--downloader-args",
                            ARIA2C_DOWNLOADER_ARGS,
                            "-o",
                            f"{temp_filepath}",
                            f"{url}",
                        ]
                        process = subprocess.Popen(cmd)
                        log_subprocess_output("YTDLP-STDOUT", process.stdout)
                        log_subprocess_output("YTDLP-STDERR", process.stderr)
                        ret_code = process.wait()
                        if ret_code == 0:
                            tmp_file_path = lecture_path + ".tmp"
                            logger.info("      > HLS Download success")
                            if use_h265:
                                codec = "hevc_nvenc" if use_nvenc else "libx265"
                                transcode = "-hwaccel cuda -hwaccel_output_format cuda".split(" ") if use_nvenc else []
                                cmd = [
                                    "ffmpeg",
                                    *transcode,
                                    "-y",
                                    "-i",
                                    lecture_path,
                                    "-c:v",
                                    codec,
                                    "-c:a",
                                    "copy",
                                    "-f",
                                    "mp4",
                                    "-metadata",
                                    'comment="Downloaded with Udemy-Downloader by Sheikh Bilal (https://github.com/sheikh-bilal65)"',
                                    tmp_file_path,
                                ]
                                process = subprocess.Popen(cmd)
                                log_subprocess_output("FFMPEG-STDOUT", process.stdout)
                                log_subprocess_output("FFMPEG-STDERR", process.stderr)
                                ret_code = process.wait()
                                if ret_code == 0:
                                    os.unlink(lecture_path)
                                    os.rename(tmp_file_path, lecture_path)
                                    logger.info("      > Encoding complete")
                                else:
                                    logger.error("      > Encoding returned non-zero return code")
                                    record_strict_failure(str(lecture_id), lecture_title, f"ffmpeg encode failed (code={ret_code})")
                        else:
                            logger.error("      > HLS Download returned non-zero return code (code=%s)", ret_code)
                            record_strict_failure(str(lecture_id), lecture_title, f"HLS download failed (code={ret_code})")
                            return
                    else:
                        ret_code = download_aria(url, chapter_dir, lecture_title + ".mp4")
                        logger.debug(f"      > Download return code: {ret_code}")
                except Exception:
                    logger.exception(f">        Error downloading lecture")
                    record_strict_failure(str(lecture_id), lecture_title, "exception downloading lecture")
            else:
                logger.info(f"      > Lecture '{lecture_title}' is already downloaded, skipping...")
        else:
            logger.error("      > Missing sources for lecture", lecture)
            record_strict_failure(str(lecture_id), lecture_title, "missing sources")


def process_quiz(udemy: Udemy, lecture, chapter_dir):
    quiz = udemy._get_quiz_with_info(lecture.get("id"))
    if quiz["_type"] == "coding-problem":
        process_coding_assignment(quiz, lecture, chapter_dir)
    else:  # Normal quiz
        process_normal_quiz(quiz, lecture, chapter_dir)


def process_normal_quiz(quiz, lecture, chapter_dir):
    lecture_title = lecture.get("lecture_title")
    lecture_index = lecture.get("lecture_index")
    lecture_file_name = sanitize_filename(lecture_title + ".html")
    lecture_path = os.path.join(chapter_dir, lecture_file_name)

    logger.info(f"  > Processing quiz {lecture_index}")
    with open("./templates/quiz_template.html", "r") as f:
        html = f.read()
        quiz_data = {
            "quiz_id": lecture["data"].get("id"),
            "quiz_description": lecture["data"].get("description"),
            "quiz_title": lecture["data"].get("title"),
            "pass_percent": lecture.get("data").get("pass_percent"),
            "questions": quiz["contents"],
        }
        html = html.replace("__data_placeholder__", json.dumps(quiz_data))
        with open(lecture_path, "w") as f:
            f.write(html)


def process_coding_assignment(quiz, lecture, chapter_dir):
    lecture_title = lecture.get("lecture_title")
    lecture_index = lecture.get("lecture_index")
    lecture_file_name = sanitize_filename(lecture_title + ".html")
    lecture_path = os.path.join(chapter_dir, lecture_file_name)

    logger.info(f"  > Processing quiz {lecture_index} (coding assignment)")

    with open("./templates/coding_assignment_template.html", "r") as f:
        html = f.read()
        quiz_data = {
            "title": lecture_title,
            "hasInstructions": quiz["hasInstructions"],
            "hasTests": quiz["hasTests"],
            "hasSolutions": quiz["hasSolutions"],
            "instructions": quiz["contents"]["instructions"],
            "tests": quiz["contents"]["tests"],
            "solutions": quiz["contents"]["solutions"],
        }
        html = html.replace("__data_placeholder__", json.dumps(quiz_data))
        with open(lecture_path, "w") as f:
            f.write(html)


def parse_new(udemy: Udemy, udemy_object: dict):
    total_chapters = udemy_object.get("total_chapters")
    total_lectures = udemy_object.get("total_lectures")
    logger.info(f"Chapter(s) ({total_chapters})")
    logger.info(f"Lecture(s) ({total_lectures})")

    course_name = str(udemy_object.get("course_id")) if id_as_course_name else udemy_object.get("course_title")
    course_dir = os.path.join(DOWNLOAD_DIR, course_name)
    if not os.path.exists(course_dir):
        os.mkdir(course_dir)

    failed_lectures = []

    for chapter in udemy_object.get("chapters"):
        current_chapter_index = int(chapter.get("chapter_index"))
        # Skip chapters not in the filter if a filter is provided
        if chapter_filter is not None and current_chapter_index not in chapter_filter:
            logger.info("Skipping chapter %s as it is not in the specified filter", current_chapter_index)
            continue

        chapter_title = chapter.get("chapter_title")
        chapter_index = chapter.get("chapter_index")
        chapter_dir = os.path.join(course_dir, chapter_title)
        if not os.path.exists(chapter_dir):
            os.mkdir(chapter_dir)
        logger.info(f"======= Processing chapter {chapter_index} of {total_chapters} =======")

        for lecture in chapter.get("lectures"):
            clazz = lecture.get("_class")

            if clazz == "quiz":
                # skip the quiz if we dont want to download it
                if not dl_quizzes:
                    continue
                process_quiz(udemy, lecture, chapter_dir)
                continue

            index = lecture.get("index")  # this is lecture_counter
            # lecture_index = lecture.get("lecture_index")  # this is the raw object index from udemy

            lecture_title = lecture.get("lecture_title")
            parsed_lecture = udemy._parse_lecture(lecture)

            lecture_extension = parsed_lecture.get("extension")
            extension = "mp4"  # video lectures dont have an extension property, so we assume its mp4
            if lecture_extension != None:
                # if the lecture extension property isnt none, set the extension to the lecture extension
                extension = lecture_extension
            lecture_file_name = sanitize_filename(lecture_title + "." + extension)
            lecture_file_name = deEmojify(lecture_file_name)
            lecture_path = os.path.join(chapter_dir, lecture_file_name)

            if not skip_lectures:
                logger.info(f"  > Processing lecture {index} of {total_lectures}")

                # Check if the lecture is already downloaded
                if os.path.isfile(lecture_path):
                    logger.info("      > Lecture '%s' is already downloaded, skipping..." % lecture_title)
                else:
                    # Check if the file is an html file
                    if extension == "html":
                        # if the html content is None or an empty string, skip it so we dont save empty html files
                        if parsed_lecture.get("html_content") != None and parsed_lecture.get("html_content") != "":
                            html_content = parsed_lecture.get("html_content").encode("utf8", "ignore").decode("utf8")
                            lecture_path = os.path.join(chapter_dir, "{}.html".format(sanitize_filename(lecture_title)))
                            try:
                                with open(lecture_path, encoding="utf8", mode="w") as f:
                                    f.write(html_content)
                            except Exception:
                                logger.exception("    > Failed to write html file")
                    else:
                        try:
                            process_lecture(parsed_lecture, lecture_path, chapter_dir)
                        except Exception:
                            logger.exception("    > Error while downloading lecture '%s'", lecture_title)

                        if not os.path.isfile(lecture_path):
                            failed_lectures.append(
                                {
                                    "lecture_id": parsed_lecture.get("id"),
                                    "lecture_title": lecture_title,
                                    "lecture_path": lecture_path,
                                    "chapter_dir": chapter_dir,
                                    "lecture_data": copy.deepcopy(parsed_lecture),
                                }
                            )

            # download subtitles for this lecture
            subtitles = parsed_lecture.get("subtitles")
            if dl_captions and subtitles != None and lecture_extension == None:
                logger.info("Processing {} caption(s)...".format(len(subtitles)))
                for subtitle in subtitles:
                    lang = subtitle.get("language")
                    if lang == caption_locale or caption_locale == "all":
                        process_caption(subtitle, lecture_title, chapter_dir)

            if dl_assets:
                assets = parsed_lecture.get("assets")
                logger.info("    > Processing {} asset(s) for lecture...".format(len(assets)))

                for asset in assets:
                    asset_type = asset.get("type")
                    filename = asset.get("filename")
                    download_url = asset.get("download_url")

                    if asset_type == "article":
                        body = asset.get("body")
                        # stip the 03d prefix
                        lecture_path = os.path.join(chapter_dir, "{}.html".format(sanitize_filename(lecture_title)))
                        try:
                            with open("./templates/article_template.html", "r") as f:
                                content = f.read()
                                content = content.replace("__title_placeholder__", lecture_title[4:])
                                content = content.replace("__data_placeholder__", body)
                                with open(lecture_path, encoding="utf8", mode="w") as f:
                                    f.write(content)
                        except Exception as e:
                            print("Failed to write html file: ", e)
                            continue
                    elif asset_type == "video":
                        logger.warning(
                            "If you're seeing this message, that means that you reached a secret area that I haven't finished! jk I haven't implemented handling for this asset type, please report this at https://github.com/sheikh-bilal65 so I can add it. When reporting, please provide the following information: "
                        )
                        logger.warning("AssetType: Video; AssetData: ", asset)
                    elif (
                        asset_type == "audio"
                        or asset_type == "e-book"
                        or asset_type == "file"
                        or asset_type == "presentation"
                        or asset_type == "ebook"
                        or asset_type == "source_code"
                    ):
                        try:
                            ret_code = download_aria(download_url, chapter_dir, filename)
                            logger.debug(f"      > Download return code: {ret_code}")
                        except Exception:
                            logger.exception("> Error downloading asset")
                    elif asset_type == "external_link":
                        # write the external link to a shortcut file
                        file_path = os.path.join(chapter_dir, f"{filename}.url")
                        file = open(file_path, "w")
                        file.write("[InternetShortcut]\n")
                        file.write(f"URL={download_url}")
                        file.close()

                        # save all the external links to a single file
                        savedirs, name = os.path.split(os.path.join(chapter_dir, filename))
                        filename = "external-links.txt"
                        filename = os.path.join(savedirs, filename)
                        file_data = []
                        if os.path.isfile(filename):
                            file_data = [
                                i.strip().lower() for i in open(filename, encoding="utf-8", errors="ignore") if i
                            ]

                        content = "\n{}\n{}\n".format(name, download_url)
                        if name.lower() not in file_data:
                            with open(filename, "a", encoding="utf-8", errors="ignore") as f:
                                f.write(content)

    if failed_lectures:
        _retry_failed_downloads(failed_lectures)

def cleanup_temp_dir(temp_path: str = TEMP_DIR) -> None:
    temp_dir = Path(temp_path)
    if not temp_dir.exists():
        return
    removed_any = False
    for child in temp_dir.iterdir():
        try:
            if child.is_file() or child.is_symlink():
                child.unlink()
                removed_any = True
            elif child.is_dir():
                shutil.rmtree(child)
                removed_any = True
        except OSError as exc:
            logger.warning("> Temp 清理失败: %s (原因: %s)", child, exc)
    if removed_any:
        logger.info("> Temp 目录已清理：%s", temp_dir)


def _print_course_info(udemy: Udemy, udemy_object: dict):
    course_title = udemy_object.get("title")
    chapter_count = udemy_object.get("total_chapters")
    lecture_count = udemy_object.get("total_lectures")

    if lecture_count > 100:
        logger.warning(
            "This course has a lot of lectures! Fetching all the information can take a long time as well as spams Udemy's servers. It is NOT recommended to continue! Are you sure you want to do this?"
        )
        yn = input("(y/n): ")
        if yn.lower() != "y":
            logger.info("Probably wise. Please remove the --info argument and try again.")
            sys.exit(0)

    logger.info("> Course: {}".format(course_title))
    logger.info("> Total Chapters: {}".format(chapter_count))
    logger.info("> Total Lectures: {}".format(lecture_count))
    logger.info("\n")

    chapters = udemy_object.get("chapters")
    for chapter in chapters:
        current_chapter_index = int(chapter.get("chapter_index"))
        # Skip chapters not in the filter if a filter is provided
        if chapter_filter is not None and current_chapter_index not in chapter_filter:
            continue

        chapter_title = chapter.get("chapter_title")
        chapter_index = chapter.get("chapter_index")
        chapter_lecture_count = chapter.get("lecture_count")
        chapter_lectures = chapter.get("lectures")

        logger.info("> Chapter: {} ({} of {})".format(chapter_title, chapter_index, chapter_count))

        for lecture in chapter_lectures:
            lecture_index = lecture.get("lecture_index")  # this is the raw object index from udemy
            lecture_title = lecture.get("lecture_title")
            parsed_lecture = udemy._parse_lecture(lecture)

            lecture_sources = parsed_lecture.get("sources")
            lecture_is_encrypted = parsed_lecture.get("is_encrypted", None)
            lecture_extension = parsed_lecture.get("extension")
            lecture_asset_count = parsed_lecture.get("assets_count")
            lecture_subtitles = parsed_lecture.get("subtitles")
            lecture_video_sources = parsed_lecture.get("video_sources")
            lecture_type = parsed_lecture.get("type")

            lecture_qualities = []

            if lecture_sources:
                lecture_sources = sorted(lecture_sources, key=lambda x: int(x.get("height")), reverse=True)
            if lecture_video_sources:
                lecture_video_sources = sorted(lecture_video_sources, key=lambda x: int(x.get("height")), reverse=True)

            if lecture_is_encrypted and lecture_video_sources != None:
                lecture_qualities = [
                    "{}@{}x{}".format(x.get("type"), x.get("width"), x.get("height")) for x in lecture_video_sources
                ]
            elif lecture_is_encrypted == False and lecture_sources != None:
                lecture_qualities = [
                    "{}@{}x{}".format(x.get("type"), x.get("height"), x.get("width")) for x in lecture_sources
                ]

            if lecture_extension:
                continue

            logger.info("  > Lecture: {} ({} of {})".format(lecture_title, lecture_index, chapter_lecture_count))
            logger.info("    > Type: {}".format(lecture_type))
            if lecture_is_encrypted != None:
                logger.info("    > DRM: {}".format(lecture_is_encrypted))
            if lecture_asset_count:
                logger.info("    > Asset Count: {}".format(lecture_asset_count))
            if lecture_subtitles:
                logger.info("    > Captions: {}".format(", ".join([x.get("language") for x in lecture_subtitles])))
            if lecture_qualities:
                logger.info("    > Qualities: {}".format(lecture_qualities))

        if chapter_index != chapter_count:
            logger.info("==========================================")


def main():
    global bearer_token, portal_name
    aria_ret_val = check_for_aria()
    if not aria_ret_val:
        logger.fatal("> Aria2c is missing from your system or path!")
        sys.exit(1)

    yt_dlp_ret_val = check_for_yt_dlp()
    if not yt_dlp_ret_val and not skip_lectures:
        logger.fatal("> yt-dlp is missing from your system or path!")
        sys.exit(1)

    ffmpeg_ret_val = check_for_ffmpeg()
    if not ffmpeg_ret_val and not skip_lectures:
        logger.fatal("> FFMPEG is missing from your system or path!")
        sys.exit(1)

    shaka_ret_val = check_for_shaka()
    if not shaka_ret_val and not skip_lectures:
        logger.fatal("> Shaka Packager is missing from your system or path!")
        sys.exit(1)

    if load_from_file:
        logger.info("> 'load_from_file' was specified, data will be loaded from json files instead of fetched")
    if save_to_file:
        logger.info("> 'save_to_file' was specified, data will be saved to json files")

    if bearer_token:
        bearer_token = bearer_token
    else:
        bearer_token = os.getenv("UDEMY_BEARER")

    udemy = Udemy(bearer_token)

    logger.info("> Fetching course information, this may take a minute...")
    if not load_from_file:
        course_id, course_info = udemy._extract_course_info(course_url)
        logger.info("> Course information retrieved!")
        if course_info and isinstance(course_info, dict):
            title = sanitize_filename(course_info.get("title"))
            course_title = course_info.get("published_title")

    logger.info("> Fetching course curriculum, this may take a minute...")
    if load_from_file:
        course_json = json.loads(
            open(os.path.join(os.getcwd(), "saved", "course_content.json"), encoding="utf8", mode="r").read()
        )
        title = course_json.get("title")
        course_title = course_json.get("published_title")
        portal_name = course_json.get("portal_name")
    else:
        course_json = udemy._extract_course_curriculum(course_url, course_id, portal_name)
        course_json["portal_name"] = portal_name

    logger.info("> Course curriculum retrieved!")
    course = course_json.get("results")
    resource = course_json.get("detail")

    if load_from_file:
        udemy_object = json.loads(
            open(os.path.join(os.getcwd(), "saved", "_udemy.json"), encoding="utf8", mode="r").read()
        )
        if info:
            _print_course_info(udemy, udemy_object)
        else:
            parse_new(udemy, udemy_object)
            if STRICT_MODE and STRICT_FAILURES:
                logger.error("> Strict mode: %d lecture(s) failed, exiting with code 1", len(STRICT_FAILURES))
                for item in STRICT_FAILURES[-20:]:
                    logger.error("> Failed lecture: %s | %s | %s", item.get("id"), item.get("title"), item.get("reason"))
                sys.exit(1)
    else:
        udemy_object = {}
        udemy_object["bearer_token"] = bearer_token
        udemy_object["course_id"] = course_id
        udemy_object["title"] = title
        udemy_object["course_title"] = course_title
        udemy_object["chapters"] = []
        chapter_index_counter = -1

        if resource:
            logger.info("> Terminating Session...")
            udemy.session.terminate()
            logger.info("> Session Terminated.")

        if course:
            logger.info("> Processing course data, this may take a minute. ")
            lecture_counter = 0
            lectures = []

            for entry in course:
                clazz = entry.get("_class")

                if clazz == "chapter":
                    # reset lecture tracking
                    if not use_continuous_lecture_numbers:
                        lecture_counter = 0
                    lectures = []

                    chapter_index = entry.get("object_index")
                    chapter_title = "{0:02d} - ".format(chapter_index) + sanitize_filename(entry.get("title"))

                    if chapter_title not in udemy_object["chapters"]:
                        udemy_object["chapters"].append(
                            {
                                "chapter_title": chapter_title,
                                "chapter_id": entry.get("id"),
                                "chapter_index": chapter_index,
                                "lectures": [],
                            }
                        )
                        chapter_index_counter += 1
                elif clazz == "lecture":
                    lecture_counter += 1
                    lecture_id = entry.get("id")
                    if len(udemy_object["chapters"]) == 0:
                        # dummy chapters to handle lectures without chapters
                        chapter_index = entry.get("object_index")
                        chapter_title = "{0:02d} - ".format(chapter_index) + sanitize_filename(entry.get("title"))
                        if chapter_title not in udemy_object["chapters"]:
                            udemy_object["chapters"].append(
                                {
                                    "chapter_title": chapter_title,
                                    "chapter_id": lecture_id,
                                    "chapter_index": chapter_index,
                                    "lectures": [],
                                }
                            )
                            chapter_index_counter += 1
                    if lecture_id:
                        logger.info(f"Processing {course.index(entry) + 1} of {len(course)}")

                        lecture_index = entry.get("object_index")
                        lecture_title = "{0:03d} ".format(lecture_counter) + sanitize_filename(entry.get("title"))

                        lectures.append(
                            {
                                "index": lecture_counter,
                                "lecture_index": lecture_index,
                                "lecture_title": lecture_title,
                                "_class": entry.get("_class"),
                                "id": lecture_id,
                                "data": entry,
                            }
                        )
                    else:
                        logger.debug("Lecture: ID is None, skipping")
                elif clazz == "quiz":
                    lecture_counter += 1
                    lecture_id = entry.get("id")
                    if len(udemy_object["chapters"]) == 0:
                        # dummy chapters to handle lectures without chapters
                        chapter_index = entry.get("object_index")
                        chapter_title = "{0:02d} - ".format(chapter_index) + sanitize_filename(entry.get("title"))
                        if chapter_title not in udemy_object["chapters"]:
                            udemy_object["chapters"].append(
                                {
                                    "chapter_title": chapter_title,
                                    "chapter_id": lecture_id,
                                    "chapter_index": chapter_index,
                                    "lectures": [],
                                }
                            )
                            chapter_index_counter += 1

                    if lecture_id:
                        logger.info(f"Processing {course.index(entry) + 1} of {len(course)}")

                        lecture_index = entry.get("object_index")
                        lecture_title = "{0:03d} ".format(lecture_counter) + sanitize_filename(entry.get("title"))

                        lectures.append(
                            {
                                "index": lecture_counter,
                                "lecture_index": lecture_index,
                                "lecture_title": lecture_title,
                                "_class": entry.get("_class"),
                                "id": lecture_id,
                                "data": entry,
                            }
                        )
                    else:
                        logger.debug("Quiz: ID is None, skipping")

                udemy_object["chapters"][chapter_index_counter]["lectures"] = lectures
                udemy_object["chapters"][chapter_index_counter]["lecture_count"] = len(lectures)

            udemy_object["total_chapters"] = len(udemy_object["chapters"])
            udemy_object["total_lectures"] = sum(
                [entry.get("lecture_count", 0) for entry in udemy_object["chapters"] if entry]
            )

        if save_to_file:
            with open(os.path.join(os.getcwd(), "saved", "_udemy.json"), encoding="utf8", mode="w") as f:
                # remove "bearer_token" from the object before writing
                udemy_object.pop("bearer_token")
                udemy_object["portal_name"] = portal_name
                f.write(json.dumps(udemy_object))
            logger.info("> Saved parsed data to json")

        if info:
            _print_course_info(udemy, udemy_object)
        else:
            parse_new(udemy, udemy_object)
            if STRICT_MODE and STRICT_FAILURES:
                logger.error("> Strict mode: %d lecture(s) failed, exiting with code 1", len(STRICT_FAILURES))
                for item in STRICT_FAILURES[-20:]:
                    logger.error("> Failed lecture: %s | %s | %s", item.get("id"), item.get("title"), item.get("reason"))
                sys.exit(1)


if __name__ == "__main__":
    # pre run parses arguments, sets up logging, and creates directories
    pre_run()
    # run main program
    try:
        main()
    finally:
        wait_for_translation_tasks()
        cleanup_temp_dir()
