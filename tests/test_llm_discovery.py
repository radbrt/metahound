import json
from unittest.mock import MagicMock, patch

from metahound.filesets import evaluate_filesets
from metahound.llm import LLMProvider, MistralProvider, get_provider
from metahound.llm_discovery import _files_prompt, suggest_filesets_llm


def _file(name, columns=None):
    properties = None
    if columns:
        properties = {col: {"type": [t]} for col, t in columns.items()}
    return {"file": name, "properties": properties}


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def complete_json(self, system, user):
        self.calls.append((system, user))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


# Heuristics can't cluster these: same feed, but the volatile part is a word
# (weekday), not a date/seq/uuid token.
WEEKDAY_FILES = [
    _file("sales_monday.csv", {"id": "integer"}),
    _file("sales_tuesday.csv", {"id": "integer"}),
    _file("sales_wednesday.csv", {"id": "integer"}),
]


class TestSuggestFilesetsLLM:
    def test_valid_suggestion_becomes_event(self):
        provider = FakeProvider({"filesets": [
            {"name": "sales", "pattern": "sales_*.csv",
             "files": ["sales_monday.csv", "sales_tuesday.csv", "sales_wednesday.csv"]},
        ]})
        events, leftover = suggest_filesets_llm(WEEKDAY_FILES, "src", provider)

        assert leftover == []
        assert len(events) == 1
        event = events[0]
        assert event["change_type"] == "fileset_suggested"
        assert event["severity"] == "info"
        assert event["object_uri"] == "fileset://src/sales"
        assert event["detail"]["via"] == "llm"
        assert event["detail"]["file_count"] == 3

    def test_hallucinated_files_are_dropped(self):
        provider = FakeProvider({"filesets": [
            {"name": "sales", "pattern": "sales_*.csv",
             "files": ["sales_monday.csv", "sales_made_up.csv"]},
        ]})
        events, leftover = suggest_filesets_llm(WEEKDAY_FILES[:2], "src", provider)
        # Only one real matching file remains — below MIN_CLUSTER_SIZE
        assert events == []
        assert len(leftover) == 2

    def test_pattern_must_actually_match_claimed_files(self):
        provider = FakeProvider({"filesets": [
            {"name": "sales", "pattern": "revenue_*.csv",
             "files": ["sales_monday.csv", "sales_tuesday.csv"]},
        ]})
        events, leftover = suggest_filesets_llm(WEEKDAY_FILES[:2], "src", provider)
        assert events == []
        assert len(leftover) == 2

    def test_invalid_pattern_is_skipped(self):
        provider = FakeProvider({"filesets": [
            {"name": None, "pattern": 42, "files": []},
            {"name": "ok", "pattern": "sales_*.csv",
             "files": ["sales_monday.csv", "sales_tuesday.csv"]},
        ]})
        events, leftover = suggest_filesets_llm(WEEKDAY_FILES[:2], "src", provider)
        assert [e["detail"]["name"] for e in events] == ["ok"]
        assert leftover == []

    def test_provider_error_degrades_gracefully(self):
        provider = FakeProvider(RuntimeError("api down"))
        events, leftover = suggest_filesets_llm(WEEKDAY_FILES, "src", provider)
        assert events == []
        assert leftover == WEEKDAY_FILES

    def test_malformed_answer_degrades_gracefully(self):
        provider = FakeProvider({"unexpected": "shape"})
        events, leftover = suggest_filesets_llm(WEEKDAY_FILES, "src", provider)
        assert events == []
        assert leftover == WEEKDAY_FILES

    def test_name_collision_with_declared_is_skipped(self):
        provider = FakeProvider({"filesets": [
            {"name": "sales", "pattern": "sales_*.csv",
             "files": ["sales_monday.csv", "sales_tuesday.csv"]},
        ]})
        events, leftover = suggest_filesets_llm(
            WEEKDAY_FILES[:2], "src", provider, declared_names={"sales"},
        )
        assert events == []
        assert len(leftover) == 2

    def test_prompt_contains_filenames_and_columns_only(self):
        provider = FakeProvider({"filesets": []})
        suggest_filesets_llm([_file("sales_monday.csv", {"id": "integer"})], "src", provider)
        _, user = provider.calls[0]
        assert "sales_monday.csv" in user
        assert "id:integer" in user
        # No connection details or data values ever reach the prompt
        assert "password" not in user.lower()


class TestEvaluateWithLLM:
    def test_llm_runs_after_heuristics_on_leftovers_only(self):
        files = [
            _file("orders_2026-07-01.csv", {"id": "integer"}),
            _file("orders_2026-07-02.csv", {"id": "integer"}),
            _file("sales_monday.csv", {"id": "integer"}),
            _file("sales_tuesday.csv", {"id": "integer"}),
        ]
        provider = FakeProvider({"filesets": [
            {"name": "sales", "pattern": "sales_*.csv",
             "files": ["sales_monday.csv", "sales_tuesday.csv"]},
        ]})
        _, events = evaluate_filesets(
            [], files, None, "src", "sftp",
            alert_unrecognized=False, infer=True, llm_provider=provider,
        )

        by_via = {e["detail"].get("via", "heuristic"): e for e in events}
        assert by_via["heuristic"]["detail"]["name"] == "orders"
        assert by_via["llm"]["detail"]["name"] == "sales"
        # The LLM only saw what heuristics could not cluster
        _, user = provider.calls[0]
        assert "orders_" not in user
        assert "sales_monday.csv" in user

    def test_no_provider_means_no_llm_pass(self):
        _, events = evaluate_filesets(
            [], WEEKDAY_FILES, None, "src", "sftp",
            alert_unrecognized=False, infer=True, llm_provider=None,
        )
        assert events == []


class TestProviders:
    def test_get_provider_without_key_returns_none(self, monkeypatch):
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.delenv("METAHOUND_LLM_PROVIDER", raising=False)
        assert get_provider() is None

    def test_get_provider_unknown_name_returns_none(self, monkeypatch):
        monkeypatch.setenv("METAHOUND_LLM_PROVIDER", "gpt9000")
        assert get_provider() is None

    def test_get_provider_with_key(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        monkeypatch.delenv("METAHOUND_LLM_PROVIDER", raising=False)
        provider = get_provider()
        assert isinstance(provider, MistralProvider)
        assert provider.model == "mistral-small-latest"

    def test_mistral_provider_parses_response(self):
        provider = MistralProvider(api_key="k")
        fake_response = MagicMock()
        fake_response.json.return_value = {
            "choices": [{"message": {"content": json.dumps({"filesets": []})}}]
        }
        with patch("requests.post", return_value=fake_response) as post:
            result = provider.complete_json("sys", "user")
        assert result == {"filesets": []}
        body = post.call_args.kwargs["json"]
        assert body["model"] == "mistral-small-latest"
        assert body["response_format"] == {"type": "json_object"}
