"""llm_utils.strip_json_markdown_fence()'in Claude'un bazen JSON'ı sardığı
markdown code fence'lerini doğru temizlediğini doğrular."""
from llm_utils import strip_json_markdown_fence


def test_strips_json_labeled_fence():
    text = '```json\n{"a": 1}\n```'

    assert strip_json_markdown_fence(text) == '{"a": 1}'


def test_strips_plain_fence():
    text = '```\n{"a": 1}\n```'

    assert strip_json_markdown_fence(text) == '{"a": 1}'


def test_leaves_unfenced_text_unchanged():
    text = '{"a": 1}'

    assert strip_json_markdown_fence(text) == '{"a": 1}'


def test_strips_surrounding_whitespace_without_fence():
    text = '  \n{"a": 1}\n  '

    assert strip_json_markdown_fence(text) == '{"a": 1}'


def test_handles_multiline_json_inside_fence():
    text = '```json\n{\n  "a": 1,\n  "b": 2\n}\n```'

    assert strip_json_markdown_fence(text) == '{\n  "a": 1,\n  "b": 2\n}'
