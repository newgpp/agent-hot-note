import os

from agent_hot_note.config import Settings


class DeepSeekProvider:
    """Read DeepSeek-compatible OpenAI env config for CrewAI/litellm."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def apply_env(self) -> None:
        os.environ["OPENAI_BASE_URL"] = self.settings.openai_base_url
        os.environ["OPENAI_MODEL"] = self.settings.openai_model
        if self.settings.openai_api_key:
            os.environ["OPENAI_API_KEY"] = self.settings.openai_api_key
