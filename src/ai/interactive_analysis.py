from __future__ import annotations

import logging
import re

from src.ai.ollama_client import OllamaClient
from src.ai.prompts import coin_alert_analysis
from src.core.config import Settings

LOGGER = logging.getLogger(__name__)


class AlertAnalysisGenerator:
    def __init__(self, settings: Settings, ollama_client: OllamaClient | None) -> None:
        self.settings = settings
        self.ollama_client = ollama_client
        self._banned_phrases = (
            "guaranteed",
            "definitely buy",
            "definitely short",
            "financial advice",
            "moon",
            "lambo",
            "100x",
            "i'm excited",
            "best regards",
        )

    async def generate(self, *, prepared_context: str, fallback_text: str, language: str = "en") -> tuple[str, str]:
        fallback_clean = self._clean_output(fallback_text)
        if not self.settings.ollama_enabled or self.ollama_client is None:
            return fallback_clean, "fallback-template"

        prompt = coin_alert_analysis(prepared_context=prepared_context, language=language)
        for model_name in self._model_candidates():
            try:
                response = await self.ollama_client.generate(
                    prompt,
                    model_name=model_name,
                    temperature=0.45,
                )
                cleaned = self._clean_output(response)
                self._validate(cleaned)
                return cleaned, model_name
            except Exception as exc:  # pragma: no cover - runtime dependent
                LOGGER.error(
                    "Interactive alert analysis rejected for model %s at %s. Falling back if needed. Error: %s",
                    model_name,
                    self.settings.ollama_base_url,
                    exc,
                )
        return fallback_clean, "fallback-template"

    def _model_candidates(self) -> list[str]:
        models = [
            self.settings.effective_ollama_analysis_model,
            self.settings.effective_ollama_writer_model,
            self.settings.ollama_model,
        ]
        return [model for idx, model in enumerate(models) if model and model not in models[:idx]]

    def _clean_output(self, text: str) -> str:
        cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        cleaned = re.sub(r"^```(?:text|markdown)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
        cleaned = cleaned.replace("__", "").replace("`", "")
        cleaned = re.sub(r"^\s*#+\s*", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip(" \n\"'")

    def _validate(self, text: str) -> None:
        if not text:
            raise RuntimeError("empty analysis output")
        lowered = text.lower()
        for phrase in self._banned_phrases:
            if phrase in lowered:
                raise RuntimeError(f"banned phrase detected: {phrase}")
        word_count = len(re.findall(r"\b[\w']+\b", text))
        if word_count < 45 or word_count > 180:
            raise RuntimeError(f"word count {word_count} outside 45-180")
        if text.count("\n") > 8:
            raise RuntimeError("analysis too long for Telegram")
