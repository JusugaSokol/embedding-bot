from __future__ import annotations

import logging
import os
import random
import time
from typing import List, TypedDict

from django.conf import settings
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from mistralai import Mistral, models


logger = logging.getLogger(__name__)

API_MAX_RETRIES = 6
API_RETRY_BASE_DELAY = 4.0
SEGMENT_BATCH_SIZE = 10


class EmbeddingState(TypedDict, total=False):
    texts: List[str]
    embeddings: List[List[float]]
    index: int


class EmbeddingAgent:
    def __init__(
        self,
        model: str = "mistral-embed",
        client: Mistral | None = None,
        request_delay: float = 2.0,
    ):
        api_key = getattr(settings, "MISTRAL_API_KEY", None) or os.getenv("MISTRAL_API_KEY")
        if not api_key:
            raise ValueError("MISTRAL_API_KEY is not configured.")
        self.client = client or Mistral(api_key=api_key)
        self.model = model
        self.request_delay = request_delay
        self.app = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(EmbeddingState)

        def embed(state: EmbeddingState) -> EmbeddingState:
            index = state.get("index", 0)
            texts = state.get("texts", [])
            if index >= len(texts):
                return state

            current_text = texts[index]

            for attempt in range(1, API_MAX_RETRIES + 1):
                try:
                    response = self.client.embeddings.create(model=self.model, inputs=[current_text])
                    break
                except models.SDKError as error:
                    message = str(error)
                    if (
                        "Status 429" in message
                        or "service_tier_capacity_exceeded" in message
                        or getattr(error, "status_code", None) == 429
                    ):
                        logger.warning(
                            "Mistral rate limit hit (attempt %s/%s): %s",
                            attempt,
                            API_MAX_RETRIES,
                            message,
                        )
                        if attempt == API_MAX_RETRIES:
                            raise
                        delay = API_RETRY_BASE_DELAY * attempt + random.uniform(0, API_RETRY_BASE_DELAY)
                        time.sleep(delay)
                        continue
                    raise

            embedding_vector = response.data[0].embedding
            embeddings = state.get("embeddings", [])
            embeddings = [*embeddings, embedding_vector]
            time.sleep(self.request_delay + random.uniform(0, self.request_delay))
            return {
                "embeddings": embeddings,
                "index": index + 1,
            }

        graph.add_node("embed", embed)
        graph.add_edge(START, "embed")

        def route(state: EmbeddingState) -> str:
            if state.get("index", 0) >= len(state.get("texts", [])):
                return END
            return "embed"

        graph.add_conditional_edges("embed", route)
        return graph.compile()

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        results: list[list[float]] = []
        for batch_start in range(0, len(texts), SEGMENT_BATCH_SIZE):
            batch = texts[batch_start : batch_start + SEGMENT_BATCH_SIZE]
            initial_state: EmbeddingState = {
                "texts": batch,
                "index": 0,
                "embeddings": [],
            }
            recursion_limit = max(len(batch) + 5, 50)
            result = self.app.invoke(initial_state, config={"recursion_limit": recursion_limit})
            results.extend(result.get("embeddings", []))
            time.sleep(self.request_delay * 2 + random.uniform(0, self.request_delay))
        return results
