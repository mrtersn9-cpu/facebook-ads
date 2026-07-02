"""Claude gibi LLM'lerin bazen JSON çıktısını sardığı markdown code
fence'lerini (```json ... ``` veya ``` ... ```) temizleyen küçük bir
yardımcı. decision_engine.py ve creative_generator.py'nin ikisi de LLM'den
"sadece JSON döndür" istese bile, model bazen yine de fence ekleyebiliyor;
bu, `json.loads()` çağrılmadan önce fence'i güvenle çıkarır."""
import re

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)


def strip_json_markdown_fence(text: str) -> str:
    """Metin ```json ... ``` ile sarılıysa fence'leri çıkarır; sarılı
    değilse metni (baştaki/sondaki boşluklar kırpılmış olarak) olduğu gibi
    döner."""
    stripped = text.strip()
    match = _FENCE_RE.match(stripped)
    if match:
        return match.group(1).strip()
    return stripped
