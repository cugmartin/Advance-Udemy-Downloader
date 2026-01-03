# -*- coding: utf-8 -*-
import os
import json
import logging
import time
from pathlib import Path
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
