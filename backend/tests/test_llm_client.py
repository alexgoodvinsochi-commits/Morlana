"""services.llm.build_client: the LLM provider is chosen by settings alone.

No test opens a connection: stream_prediction talks to an httpx MockTransport.
The test container gets the owner's .env as its environment, so every variable the
client can read is cleared first, including the openai SDK's own fallbacks: with an
empty LLM_PROJECT, OPENAI_PROJECT_ID would otherwise become the OpenAI-Project header.
"""
import json

import httpx
import pytest

CLIENT_ENV = (
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_PROJECT",
    "LLM_DATA_LOGGING",
    "LLM_FREE_MODEL",
    "LLM_PREMIUM_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_ORG_ID",
    "OPENAI_PROJECT_ID",
)

TEST_KEY = "test-llm-key"
FOLDER = "b1gtestfolder"
YANDEX_BASE_URL = "https://ai.api.cloud.yandex.net/v1"
YANDEX_ENV = {
    "LLM_API_KEY": TEST_KEY,
    "LLM_BASE_URL": YANDEX_BASE_URL,
    "LLM_PROJECT": FOLDER,
    "LLM_DATA_LOGGING": "false",
    "LLM_FREE_MODEL": f"gpt://{FOLDER}/aliceai-llm-flash",
    "LLM_PREMIUM_MODEL": f"gpt://{FOLDER}/aliceai-llm",
}

REPLY_CHUNKS = ["Карта говорит: ", "да."]
SSE_REPLY = "".join(
    "data: "
    + json.dumps(
        {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "test",
            "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
        },
        ensure_ascii=False,
    )
    + "\n\n"
    for text in REPLY_CHUNKS
) + "data: [DONE]\n\n"


def _settings_from_env(monkeypatch, **env):
    """Point services.llm at Settings read from exactly `env`, the way the app reads them."""
    import services.llm
    from config import Settings

    for name in CLIENT_ENV:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    settings = Settings(_env_file=None)
    monkeypatch.setattr(services.llm, "settings", settings)
    return settings


MESSAGES = [
    {"role": "system", "content": "Ты таролог. Карты:\nГлавная карта: Шут"},
    {"role": "user", "content": "Что меня ждёт?"},
]


def _default_spread():
    from services.spreads import spread_registry

    return spread_registry.default


async def _predict(
    monkeypatch, client, *, is_premium: bool = False, spread=None
) -> tuple[str, httpx.Request]:
    """The real stream_prediction against a fake provider: the text and the one request it got."""
    import services.llm

    sent: list[httpx.Request] = []

    def provider(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=SSE_REPLY)

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http_client:
        monkeypatch.setattr(services.llm, "client", client.with_options(http_client=http_client))
        chunks = [
            chunk
            async for chunk in services.llm.stream_prediction(
                messages=MESSAGES, spread=spread or _default_spread(), is_premium=is_premium
            )
        ]

    assert len(sent) == 1
    return "".join(chunks), sent[0]


async def test_without_an_api_key_there_is_no_client_and_the_stub_answers(monkeypatch):
    import services.llm

    _settings_from_env(monkeypatch, LLM_BASE_URL=YANDEX_BASE_URL, LLM_PROJECT=FOLDER)

    assert services.llm.build_client() is None
    monkeypatch.setattr(services.llm, "client", None)
    chunks = [
        c
        async for c in services.llm.stream_prediction(messages=MESSAGES, spread=_default_spread())
    ]
    assert chunks == ["[Модуль ИИ не настроен. Установите LLM_API_KEY в .env]"]


@pytest.mark.parametrize(
    "env, url",
    [
        ({}, "https://api.openai.com/v1/chat/completions"),
        (
            {"LLM_BASE_URL": "https://llm.example.com/v1", "LLM_FREE_MODEL": "mimo-v2.5", "LLM_DATA_LOGGING": "true"},
            "https://llm.example.com/v1/chat/completions",
        ),
    ],
    ids=["defaults", "mimo-style"],
)
async def test_without_yandex_settings_there_is_no_project_and_no_logging_header(monkeypatch, env, url):
    import services.llm

    settings = _settings_from_env(monkeypatch, LLM_API_KEY=TEST_KEY, **env)
    assert settings.LLM_PROJECT == ""
    assert settings.LLM_DATA_LOGGING is True
    client = services.llm.build_client()
    assert client.project is None

    text, request = await _predict(monkeypatch, client)

    assert text == "".join(REPLY_CHUNKS)
    assert str(request.url) == url
    assert request.headers["authorization"] == f"Bearer {TEST_KEY}"
    assert "openai-project" not in request.headers
    assert "x-data-logging-enabled" not in request.headers
    assert json.loads(request.content)["model"] == settings.LLM_FREE_MODEL


@pytest.mark.parametrize("is_premium, model", [(False, "aliceai-llm-flash"), (True, "aliceai-llm")])
async def test_yandex_settings_reach_the_provider(monkeypatch, is_premium, model):
    import services.llm

    settings = _settings_from_env(monkeypatch, **YANDEX_ENV)
    assert settings.LLM_DATA_LOGGING is False
    client = services.llm.build_client()
    assert str(client.base_url) == f"{YANDEX_BASE_URL}/"
    assert client.project == FOLDER

    text, request = await _predict(monkeypatch, client, is_premium=is_premium)

    assert text == "".join(REPLY_CHUNKS)
    assert str(request.url) == f"{YANDEX_BASE_URL}/chat/completions"
    assert request.headers["authorization"] == f"Bearer {TEST_KEY}"
    assert request.headers["openai-project"] == FOLDER
    assert request.headers["x-data-logging-enabled"] == "false"
    body = json.loads(request.content)
    assert body["model"] == f"gpt://{FOLDER}/{model}"
    assert body["stream"] is True
    assert body["messages"] == MESSAGES
    # The spread, not the code, sets the sampling parameters.
    assert (body["max_tokens"], body["temperature"]) == (2048, 0.7)


async def test_the_spread_sets_max_tokens_and_temperature(monkeypatch):
    """A spread file is enough to change what the provider is asked for."""
    import services.llm

    _settings_from_env(monkeypatch, **YANDEX_ENV)
    spread = _default_spread().model_copy(update={"max_tokens": 321, "temperature": 0.11})

    _, request = await _predict(monkeypatch, services.llm.build_client(), spread=spread)

    body = json.loads(request.content)
    assert (body["max_tokens"], body["temperature"]) == (321, 0.11)


async def test_llm_project_wins_over_the_sdk_environment_fallback(monkeypatch):
    import services.llm

    _settings_from_env(monkeypatch, **YANDEX_ENV)
    monkeypatch.setenv("OPENAI_PROJECT_ID", "proj_from_the_environment")

    assert services.llm.build_client().project == FOLDER
