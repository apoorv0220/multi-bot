from typing import Any

import openai


class OpenAIClientAdapter:
    def __init__(self):
        self.client = openai

    def create_embedding(self, *, model: str, input_text: str) -> Any:
        return self.client.embeddings.create(model=model, input=input_text)

    def create_chat_completion(self, *, model: str, messages: list[dict]) -> Any:
        return self.client.chat.completions.create(model=model, messages=messages)

    def create_structured_completion(
        self,
        *,
        model: str,
        messages: list[dict],
        response_format: dict | None = None,
    ) -> Any:
        kwargs: dict = {"model": model, "messages": messages}
        if response_format is not None:
            kwargs["response_format"] = response_format
        else:
            kwargs["response_format"] = {"type": "json_object"}
        return self.client.chat.completions.create(**kwargs)
