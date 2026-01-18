# -*- coding: utf-8 -*-
import os
import json
import logging
import time
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Tuple
import deepl

logger = logging.getLogger("udemy-downloader")

class SubtitleTranslator:
    """Handles translation of subtitles using DeepL API with caching and retry logic"""
    
    def __init__(self, api_key=None, cache_dir=".translation_cache"):
        """
        Initialize the translator with DeepL API key
        
        Args:
            api_key: DeepL API key (if None, will try to load from env)
            cache_dir: Directory to store translation cache
        """
        self.api_key = api_key or os.getenv("DEEPL_API_KEY")
        if not self.api_key:
            raise ValueError("DEEPL_API_KEY not found in environment or provided")
        
        self.translator = deepl.Translator(self.api_key)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.cache_file = self.cache_dir / "translation_cache.json"
        self.cache = self._load_cache()
        self._cache_lock = threading.Lock()
        
    def _load_cache(self):
        """Load translation cache from disk"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load translation cache: {e}")
                return {}
        return {}
    
    def _save_cache(self):
        """Save translation cache to disk"""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save translation cache: {e}")
    
    def _get_cache_key(self, text, source_lang, target_lang):
        """Generate cache key for a translation"""
        return f"{source_lang}:{target_lang}:{text}"
    
    def translate_text(self, text, source_lang="EN", target_lang="ZH", max_retries=3):
        """
        Translate text with caching and retry logic
        
        Args:
            text: Text to translate
            source_lang: Source language code (default: EN)
            target_lang: Target language code (default: ZH)
            max_retries: Maximum number of retry attempts
            
        Returns:
            Translated text or None if translation fails
        """
        if not text or not text.strip():
            return text
        
        # Check cache first
        cache_key = self._get_cache_key(text, source_lang, target_lang)
        if cache_key in self.cache:
            logger.debug(f"Using cached translation for: {text[:50]}...")
            return self.cache[cache_key]
        
        # Attempt translation with retries
        for attempt in range(max_retries):
            try:
                result = self.translator.translate_text(
                    text, 
                    source_lang=source_lang, 
                    target_lang=target_lang
                )
                translated = result.text
                
                # Cache the result
                self.cache[cache_key] = translated
                self._save_cache()
                
                return translated
                
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Translation attempt {attempt + 1} failed: {e}. Retrying...")
                    time.sleep(1)  # Wait before retry
                else:
                    logger.error(f"Translation failed after {max_retries} attempts: {e}")
                    return None
        
        return None
    
    def translate_batch(self, texts, source_lang="EN", target_lang="ZH", max_retries=3):
        """
        Translate multiple texts with progress logging
        
        Args:
            texts: List of texts to translate
            source_lang: Source language code
            target_lang: Target language code
            max_retries: Maximum retry attempts per text
            
        Returns:
            List of translated texts (None for failed translations)
        """
        results = []
        total = len(texts)
        
        for idx, text in enumerate(texts, 1):
            logger.info(f"    > Translating subtitle {idx}/{total}...")
            translated = self.translate_text(text, source_lang, target_lang, max_retries)
            results.append(translated)
            
        return results


class OpenAICompatibleTranslator:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        request_timeout: Optional[float] = None,
        chunk_size: Optional[int] = None,
        cache_dir: str = ".translation_cache",
        max_retries: Optional[int] = None,
        retry_delay: Optional[float] = None,
    ):
        self.api_key = (
            api_key
            or os.getenv("SUBTITLE_TRANSLATE_API_KEY")
            or os.getenv("TRANSLATE_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )
        self.base_url = (
            base_url
            or os.getenv("SUBTITLE_TRANSLATE_BASE_URL")
            or os.getenv("TRANSLATE_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
        )
        self.model = (
            model
            or os.getenv("SUBTITLE_TRANSLATE_MODEL")
            or os.getenv("TRANSLATE_MODEL")
            or "gpt-4o-mini"
        )
        self.request_timeout = request_timeout
        if self.request_timeout is None:
            timeout_env = os.getenv("SUBTITLE_TRANSLATE_REQUEST_TIMEOUT") or os.getenv(
                "TRANSLATE_REQUEST_TIMEOUT"
            )
            self.request_timeout = float(timeout_env) if timeout_env else 60.0
 
        self.chunk_size = chunk_size
        if self.chunk_size is None:
            chunk_env = os.getenv("SUBTITLE_TRANSLATE_CHUNK_SIZE") or os.getenv("TRANSLATE_CHUNK_SIZE")
            self.chunk_size = int(chunk_env) if chunk_env else 2800
 
        self.max_retries = max_retries
        if self.max_retries is None:
            retries_env = os.getenv("SUBTITLE_TRANSLATE_MAX_RETRIES") or os.getenv("TRANSLATE_MAX_RETRIES")
            self.max_retries = int(retries_env) if retries_env else 3
 
        self.retry_delay = retry_delay
        if self.retry_delay is None:
            delay_env = os.getenv("SUBTITLE_TRANSLATE_RETRY_DELAY") or os.getenv("TRANSLATE_RETRY_DELAY")
            self.retry_delay = float(delay_env) if delay_env else 5.0
 
        workers_env = os.getenv("SUBTITLE_TRANSLATE_MAX_WORKERS") or os.getenv("TRANSLATE_MAX_WORKERS")
        try:
            self.max_workers = max(1, int(workers_env)) if workers_env else 1
        except ValueError:
            self.max_workers = 1
 
        if not self.api_key:
            raise ValueError(
                "TRANSLATE_API_KEY/OPENAI_API_KEY not found in environment or provided"
            )
 
        try:
            from openai import (
                APIConnectionError,
                APIError,
                APITimeoutError,
                OpenAI,
                RateLimitError,
            )
        except ImportError as e:
            raise ImportError(
                "Missing dependency 'openai'. Please install it (pip install openai)."
            ) from e
 
        self._retryable_errors = (APITimeoutError, APIConnectionError, RateLimitError, APIError)
 
        client_kwargs = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        if self.request_timeout:
            client_kwargs["timeout"] = self.request_timeout
        self.client = OpenAI(**client_kwargs)
 
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.cache_file = self.cache_dir / "translation_cache.json"
        self.cache = self._load_cache()
        self._cache_lock = threading.Lock()
 
    def _load_cache(self):
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load translation cache: {e}")
                return {}
        return {}
 
    def _save_cache(self):
        with self._cache_lock:
            try:
                with open(self.cache_file, "w", encoding="utf-8") as f:
                    json.dump(self.cache, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"Failed to save translation cache: {e}")
 
    def _get_cache_key(self, text: str, source_lang: str, target_lang: str):
        return f"openai:{self.model}:{source_lang}:{target_lang}:{text}"
 
    def _extract_json_payload(self, content: str) -> str:
        if not content:
            return ""
        match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        match = re.search(r"```\s*(.*?)\s*```", content, re.DOTALL)
        if match:
            return match.group(1).strip()
        return content.strip()

    def _parse_json_array(self, payload: str, expected_len: int) -> List[Optional[str]]:
        def _coerce_list(value):
            if not isinstance(value, list):
                raise ValueError("Response is not a JSON array")
            if len(value) != expected_len:
                raise ValueError("Response array length mismatch")
            coerced = []
            for item in value:
                if item is None:
                    coerced.append(None)
                else:
                    coerced.append(str(item))
            return coerced

        if not payload:
            raise ValueError("Empty translation payload")

        try:
            parsed = json.loads(payload)
            return _coerce_list(parsed)
        except (json.JSONDecodeError, ValueError):
            pass

        bracket_match = re.search(r"\[\s*[\s\S]*\s*\]", payload)
        if bracket_match:
            try:
                parsed = json.loads(bracket_match.group(0))
                return _coerce_list(parsed)
            except (json.JSONDecodeError, ValueError):
                pass

        stripped_lines = [
            line.strip()
            for line in payload.splitlines()
            if line.strip()
        ]
        if len(stripped_lines) == expected_len:
            return stripped_lines

        raise ValueError("Unable to parse translation payload")
 
    def _translate_batch_uncached(self, texts: List[str], source_lang: str, target_lang: str) -> List[Optional[str]]:
        system_msg = (
            "You are a translation engine. Translate each line faithfully from "
            f"{source_lang} to {target_lang}. Preserve line breaks within each item. "
            "Return ONLY a JSON array of strings with the same length and order as the input array."
        )
        user_msg = json.dumps(
            {"source_lang": source_lang, "target_lang": target_lang, "lines": texts},
            ensure_ascii=False,
        )
 
        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    temperature=0.0,
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_msg},
                    ],
                )
                content = response.choices[0].message.content or ""
                payload = self._extract_json_payload(content)
                parsed = self._parse_json_array(payload, len(texts))
                return parsed
            except self._retryable_errors as err:
                last_error = err
                if attempt >= self.max_retries:
                    break
                delay = self.retry_delay * attempt
                time.sleep(delay)
            except Exception as err:
                last_error = err
                break
 
        if last_error:
            raise last_error
        raise RuntimeError("Translation failed")
 
    def _iter_char_limited_batches(self, pairs: List[Tuple[int, str]], max_chars: int):
        batch: List[Tuple[int, str]] = []
        current = 0
        for idx, text in pairs:
            size = len(text)
            if batch and current + size > max_chars:
                yield batch
                batch = [(idx, text)]
                current = size
                continue
            batch.append((idx, text))
            current += size
        if batch:
            yield batch
 
    def translate_batch(self, texts, source_lang="EN", target_lang="ZH", max_retries=3):
        if not texts:
            return []

        original_max_retries = self.max_retries
        if max_retries is not None:
            try:
                self.max_retries = int(max_retries)
            except (TypeError, ValueError):
                self.max_retries = original_max_retries
        try:
            results: List[Optional[str]] = [None] * len(texts)
            to_translate: List[Tuple[int, str]] = []

            for i, text in enumerate(texts):
                if text is None or not str(text).strip():
                    results[i] = text
                    continue
                t = str(text)
                key = self._get_cache_key(t, source_lang, target_lang)
                cached = self.cache.get(key)
                if cached is not None:
                    results[i] = cached
                else:
                    to_translate.append((i, t))

            if not to_translate:
                return results

            batches = list(self._iter_char_limited_batches(to_translate, max_chars=self.chunk_size))
            total_batches = len(batches)
            logger.info(
                "    > [Gemini] Preparing %d subtitle(s) across %d batch(es) (chunk<=%d chars, workers=%d)",
                len(to_translate),
                total_batches,
                self.chunk_size,
                min(self.max_workers, total_batches),
            )

            cache_updated = False

            def process_batch(batch_idx: int, batch: List[Tuple[int, str]]):
                batch_indices = [i for i, _ in batch]
                batch_texts = [t for _, t in batch]
                char_count = sum(len(t) for t in batch_texts)
                logger.info(
                    "    > [Gemini] Batch %d/%d: %d subtitles (~%d chars) ...",
                    batch_idx,
                    total_batches,
                    len(batch_texts),
                    char_count,
                )
                start = time.time()
                translated = self._translate_batch_uncached(batch_texts, source_lang, target_lang)
                duration = time.time() - start
                logger.info(
                    "    > [Gemini] Batch %d/%d completed in %.2fs",
                    batch_idx,
                    total_batches,
                    duration,
                )
                return batch_idx, batch_indices, translated

            if self.max_workers > 1 and total_batches > 1:
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    future_map = {
                        executor.submit(process_batch, idx, batch): idx
                        for idx, batch in enumerate(batches, start=1)
                    }
                    for future in as_completed(future_map):
                        batch_idx, batch_indices, translated = future.result()
                        for i, zh in zip(batch_indices, translated):
                            results[i] = zh
                            if zh is not None:
                                key = self._get_cache_key(str(texts[i]), source_lang, target_lang)
                                with self._cache_lock:
                                    self.cache[key] = zh
                                    cache_updated = True
            else:
                for idx, batch in enumerate(batches, start=1):
                    batch_indices = [i for i, _ in batch]
                    batch_texts = [t for _, t in batch]
                    try:
                        batch_idx, _, translated = process_batch(idx, batch)
                        for i, zh in zip(batch_indices, translated):
                            results[i] = zh
                            if zh is not None:
                                key = self._get_cache_key(str(texts[i]), source_lang, target_lang)
                                with self._cache_lock:
                                    self.cache[key] = zh
                                    cache_updated = True
                    except Exception as e:
                        logger.error(f"Translation batch failed: {e}")
                        for i in batch_indices:
                            results[i] = None

            if cache_updated:
                self._save_cache()

            return results
        finally:
            self.max_retries = original_max_retries


def create_translator(provider: Optional[str] = None, cache_dir: str = ".translation_cache"):
    normalized = (
        provider
        or os.getenv("SUBTITLE_TRANSLATE_PROVIDER")
        or os.getenv("TRANSLATE_PROVIDER")
        or ""
    ).strip().lower()
    if normalized in ("", "none", "false", "0"):
        deepl_key = os.getenv("DEEPL_API_KEY")
        if deepl_key:
            return SubtitleTranslator(api_key=deepl_key, cache_dir=cache_dir)
        raise ValueError("No translation provider configured")
    if normalized in ("deepl", "deepl-api"):
        return SubtitleTranslator(api_key=os.getenv("DEEPL_API_KEY"), cache_dir=cache_dir)
    if normalized in ("gemini", "openai", "openai-compatible", "llm"):
        return OpenAICompatibleTranslator(cache_dir=cache_dir)
    raise ValueError(f"Unknown translation provider: {provider}")
