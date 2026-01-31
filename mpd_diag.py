import argparse
import os
import re
from http.cookiejar import MozillaCookieJar
from pathlib import Path

import requests
from dotenv import load_dotenv


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _load_cookies() -> MozillaCookieJar | None:
    for p in ("cookies.txt", "cookie.txt"):
        if os.path.exists(p):
            cj = MozillaCookieJar(p)
            cj.load(ignore_discard=True, ignore_expires=True)
            return cj
    return None


def _strip_auth_headers(headers: dict) -> dict:
    return {
        k: v
        for k, v in (headers or {}).items()
        if k.lower() not in {"authorization", "x-udemy-authorization", "cookie"}
    }


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "url",
        nargs="?",
        default="",
        type=str,
        help="Full index.mpd URL (including token=...). If omitted, will be extracted from logs.",
    )
    parser.add_argument(
        "--from-log",
        type=str,
        default="",
        help="Optional log file path to extract index.mpd URL from (defaults to latest logs/*.log)",
    )
    parser.add_argument(
        "--engine",
        type=str,
        default=os.getenv("MPD_DIAG_ENGINE", "requests"),
        choices=("requests", "curl_cffi"),
        help="HTTP engine to use: requests or curl_cffi (Chrome impersonation)",
    )
    parser.add_argument(
        "--portal",
        type=str,
        default=os.getenv("UDEMY_PORTAL", "cognizant"),
        help="Portal subdomain (e.g. cognizant) used for Origin/Referer",
    )
    parser.add_argument(
        "--referer",
        type=str,
        default="",
        help="Optional Referer override (e.g. https://<portal>.udemy.com/course/<course>/learn/)",
    )
    parser.add_argument(
        "--origin",
        type=str,
        default="",
        help="Optional Origin override (e.g. https://<portal>.udemy.com)",
    )
    parser.add_argument(
        "--no-proxy",
        action="store_true",
        help="Disable system/environment proxy settings for this diagnostic request",
    )
    args = parser.parse_args()

    connect_timeout = _int_env("UDEMY_CONNECT_TIMEOUT", 30)
    read_timeout = _int_env("UDEMY_READ_TIMEOUT", 180)

    no_proxy_mode = args.no_proxy or os.getenv("NO_PROXY_MODE", "0").strip().lower() in ("1", "true", "yes")

    s = None
    if args.engine == "requests":
        s = requests.Session()
        if no_proxy_mode:
            s.trust_env = False

    bearer = (os.getenv("UDEMY_BEARER") or "").strip().strip('"')
    cj = _load_cookies()

    origin = args.origin.strip() or f"https://{args.portal}.udemy.com"
    referer = args.referer.strip() or f"https://{args.portal}.udemy.com/"

    base_headers = {
        "User-Agent": os.getenv(
            "UDEMY_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ),
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate",
        "Origin": origin,
        "Referer": referer,
        "Host": f"{args.portal}.udemy.com",
    }

    auth_headers = dict(base_headers)
    if bearer:
        auth_headers["Authorization"] = f"Bearer {bearer}"
        auth_headers["X-Udemy-Authorization"] = f"Bearer {bearer}"

    no_auth_headers = _strip_auth_headers(auth_headers)

    attempts: list[tuple[str, dict, object]] = []
    attempts.append(("auth-with-cookies", auth_headers, cj))
    attempts.append(("no-auth-with-cookies", no_auth_headers, cj))
    attempts.append(("auth-no-cookies", auth_headers, None))
    attempts.append(("no-auth-no-cookies", no_auth_headers, None))

    url = (args.url or "").strip()
    if not url:
        log_path: Path | None = None
        if args.from_log.strip():
            log_path = Path(args.from_log.strip())
        else:
            logs_dir = Path("logs")
            if logs_dir.exists():
                logs = sorted(logs_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
                log_path = logs[0] if logs else None

        if not log_path or not log_path.exists():
            raise SystemExit("No MPD URL provided and no log file found. Provide URL or --from-log.")

        text = log_path.read_text(encoding="utf-8", errors="replace")
        matches = re.findall(r"https?://[^\s\"]+index\.mpd\?[^\s\"]+", text)
        if not matches:
            raise SystemExit(f"No index.mpd URL found in log file: {log_path}")
        url = matches[-1]

    def _redact(u: str) -> str:
        return re.sub(r"(token=)[^&]+", r"\1<redacted>", u)

    print("[mpd_diag] url:")
    print(_redact(url))
    if args.engine == "requests":
        print("[mpd_diag] proxy:", "disabled" if not s.trust_env else "enabled")
    else:
        print("[mpd_diag] proxy:", "disabled" if no_proxy_mode else "enabled (from env if set)")
    print("[mpd_diag] cookies:", "loaded" if cj is not None else "none")
    print("[mpd_diag] bearer:", "set" if bool(bearer) else "empty")
    print("[mpd_diag] timeout:", (connect_timeout, read_timeout))

    proxies = None
    if not no_proxy_mode:
        https_proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
        http_proxy = os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
        if https_proxy or http_proxy:
            proxies = {}
            if http_proxy:
                proxies["http"] = http_proxy
            if https_proxy:
                proxies["https"] = https_proxy

    for label, headers, cookies in attempts:
        try:
            if args.engine == "requests":
                r = s.get(url, headers=headers, cookies=cookies, timeout=(connect_timeout, read_timeout))
            else:
                try:
                    from curl_cffi import requests as c_requests
                except Exception as import_exc:
                    raise RuntimeError(
                        "curl_cffi is not installed. Install it with: python -m pip install curl_cffi"
                    ) from import_exc

                r = c_requests.request(
                    "GET",
                    url,
                    headers=headers,
                    cookies=cookies,
                    timeout=(connect_timeout, read_timeout),
                    proxies=proxies,
                    impersonate="chrome",
                )
            ct = (r.headers.get("Content-Type") or "").strip()
            snippet = ""
            try:
                snippet = (r.text or "")[:220].replace("\n", " ").replace("\r", " ")
            except Exception:
                snippet = ""

            print("\n==>", label)
            print("status:", r.status_code, r.reason)
            if ct:
                print("content-type:", ct)
            if r.status_code >= 400:
                print("body-snippet:", snippet)
            else:
                print("ok: received", len(r.content), "bytes")
        except KeyboardInterrupt:
            print("\n==>", label)
            print("error: KeyboardInterrupt")
            return 130
        except Exception as exc:
            print("\n==>", label)
            print("error:", repr(exc))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
