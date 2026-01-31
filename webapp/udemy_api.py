import logging
import os
import threading
from typing import Dict, List

import main as downloader_main


logger = logging.getLogger("webapp.udemy_api")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

_lock = threading.Lock()
SAMPLE_VIDEO_LIMIT = 5
MAX_PAGE_FETCHES = 3

INSPECTION_CURRICULUM_PARAMS = {
    "fields[lecture]": "title,object_index,asset",
    "fields[quiz]": "title,object_index,type",
    "fields[practice]": "title,object_index",
    "fields[chapter]": "title,object_index",
    "fields[asset]": "asset_type,course_is_drmed,media_sources,stream_urls",
    "caching_intent": True,
    "page_size": "50",
}


class UdemyInspectionError(Exception):
    """Raised when the Udemy API inspection fails."""


def _ensure_logger():
    if downloader_main.logger is None:
        downloader_main.logger = logger


def _apply_proxy_settings() -> None:
    no_proxy = os.getenv("NO_PROXY_MODE", "0").strip().lower() in ("1", "true", "yes")
    if not no_proxy:
        return
    downloader_main.DISABLE_PROXY = True
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        try:
            os.environ.pop(k, None)
        except Exception:
            pass


def inspect_course(course_url: str, bearer_token: str) -> Dict[str, bool]:
    """
    Fetch course metadata and determine whether any lecture is DRM protected.

    Returns:
        {"is_drm": bool}
    """
    if not course_url or not bearer_token:
        raise UdemyInspectionError("course_url and bearer_token are required")

    logger.info("inspect_course start url=%s", course_url)
    with _lock:
        try:
            _ensure_logger()
            _apply_proxy_settings()
            udemy = downloader_main.Udemy(bearer_token)
            course_id, course_info = udemy._extract_course_info(course_url)
            if not course_id:
                raise UdemyInspectionError("Unable to resolve course information. Check enrollment or URL.")
            logger.info("Resolved course id=%s portal=%s", course_id, downloader_main.portal_name)

            curriculum_url = downloader_main.CURRICULUM_ITEMS_URL.format(
                portal_name=downloader_main.portal_name, course_id=course_id
            )

            sampled = 0
            pages_fetched = 0
            saw_video = False

            def build_stub(entry: dict) -> dict:
                return {
                    "index": entry.get("object_index"),
                    "lecture_index": entry.get("object_index"),
                    "lecture_title": entry.get("title") or f"Lecture {entry.get('object_index')}",
                    "_class": entry.get("_class"),
                    "id": entry.get("id"),
                    "data": entry,
                }

            def entry_is_video(entry: dict) -> bool:
                asset = entry.get("asset") or {}
                asset_type = asset.get("asset_type") or asset.get("assetType")
                return isinstance(asset_type, str) and asset_type.lower() == "video"

            def try_decide_by_course_is_drmed(entries: List[dict]) -> Dict[str, bool] | None:
                present = 0
                true_count = 0
                false_count = 0
                for entry in entries:
                    asset = entry.get("asset") or {}
                    if not isinstance(asset, dict):
                        continue
                    if "course_is_drmed" not in asset:
                        continue
                    present += 1
                    if asset.get("course_is_drmed") is True:
                        true_count += 1
                    elif asset.get("course_is_drmed") is False:
                        false_count += 1

                logger.info(
                    "course_is_drmed present=%s/%s true=%s false=%s",
                    present,
                    len(entries),
                    true_count,
                    false_count,
                )

                if true_count > 0:
                    return {"is_drm": True}
                if present > 0 and false_count > 0 and true_count == 0:
                    return {"is_drm": False}
                return None

            def sample_videos(entries: List[dict]) -> Dict[str, bool] | None:
                nonlocal sampled, saw_video
                for entry in entries:
                    if entry.get("_class") != "lecture":
                        continue
                    if not entry_is_video(entry):
                        continue
                    saw_video = True
                    parsed = udemy._parse_lecture(build_stub(entry))
                    if parsed.get("is_encrypted"):
                        logger.info(
                            "Detected DRM via video lecture index=%s title=%s",
                            entry.get("object_index"),
                            entry.get("title"),
                        )
                        return {"is_drm": True}
                    sampled += 1
                    if sampled >= SAMPLE_VIDEO_LIMIT:
                        logger.info("Sample limit reached (%s).", SAMPLE_VIDEO_LIMIT)
                        return {"is_drm": False}
                return None

            course_json = udemy.session._get(curriculum_url, INSPECTION_CURRICULUM_PARAMS).json()
            pages_fetched += 1
            results = course_json.get("results", [])
            next_url = course_json.get("next")
            logger.info("Fetched curriculum page=%s entries=%s", pages_fetched, len(results))

            decision = try_decide_by_course_is_drmed(results)
            if decision is not None:
                udemy.session.terminate()
                logger.info("Course inspected via course_is_drmed: is_drm=%s", decision.get("is_drm"))
                return decision

            decision = sample_videos(results)
            if decision is not None:
                udemy.session.terminate()
                logger.info("Course inspected via video sampling: is_drm=%s", decision.get("is_drm"))
                return decision

            while next_url and pages_fetched < MAX_PAGE_FETCHES and sampled < SAMPLE_VIDEO_LIMIT:
                logger.info("Fetching additional curriculum page=%s", pages_fetched + 1)
                course_json = udemy.session._get(next_url).json()
                pages_fetched += 1
                results = course_json.get("results", [])
                next_url = course_json.get("next")
                logger.info("Fetched curriculum page=%s entries=%s", pages_fetched, len(results))

                decision = try_decide_by_course_is_drmed(results)
                if decision is not None:
                    udemy.session.terminate()
                    logger.info("Course inspected via course_is_drmed: is_drm=%s", decision.get("is_drm"))
                    return decision

                decision = sample_videos(results)
                if decision is not None:
                    udemy.session.terminate()
                    logger.info("Course inspected via video sampling: is_drm=%s", decision.get("is_drm"))
                    return decision

            if not saw_video:
                logger.info("No video lectures found within inspected pages; returning non-DRM.")
            else:
                logger.info(
                    "No DRM detected after sampling videos=%s pages=%s; returning non-DRM.",
                    sampled,
                    pages_fetched,
                )
            udemy.session.terminate()
            return {"is_drm": False}

        except UdemyInspectionError:
            raise
        except SystemExit as exc:
            raise UdemyInspectionError(
                "Udemy API 拒绝访问（可能是 Bearer Token 失效或无权限）。请检查后重试。"
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive handling
            logger.exception("Failed to inspect course")
            raise UdemyInspectionError(str(exc)) from exc
