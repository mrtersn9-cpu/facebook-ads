# Meta Ads AI Agent

Facebook/Meta Ads Manager kampanyalarını Marketing API v25.0 üzerinden okuyan,
performansı Claude API ile yorumlayıp aksiyon önerileri üreten, bu önerileri
sabit kod-tabanlı guardrail'lerden geçiren ve ancak öyle uygulayan bir reklam
optimizasyon ajanı. Faz faz geliştirme planı için [CLAUDE.md](CLAUDE.md)
dosyasına bakın.

## Kurulum

```bash
pip install -r requirements.txt
cp .env.example .env
# .env dosyasını gerçek (veya test) değerlerle doldurun
```

## Çalıştırma

```bash
python main.py --once   # boru hattını bir kez çalıştır
python main.py          # RUN_INTERVAL_HOURS aralığıyla sürekli çalıştır
```

## Guardrail Mantığı

Karar motorunun (Claude) ürettiği her aksiyon önerisi, uygulanmadan önce
`guardrails.py` içindeki sabit kod-tabanlı kontrollerden geçer:

- Bilinmeyen/uydurulmuş `adset_id` içeren aksiyonlar reddedilir.
- `MIN_SPEND_BEFORE_ACTION` altındaki ad set'lere (pause hariç) aksiyon uygulanmaz.
- Bütçe değişiklikleri `MAX_BUDGET_CHANGE_PERCENT` ile sınırlanır (clamp).
- Toplam önerilen günlük bütçe `MAX_DAILY_BUDGET_TOTAL`'ı aşarsa, o run için
  **hiçbir aksiyon uygulanmaz** (fail-closed).
- Bir run'da en fazla `MAX_ACTIONS_PER_RUN` aksiyon uygulanır.

`DRY_RUN=true` iken hiçbir gerçek API yazma çağrısı yapılmaz; aksiyonlar
sadece `logs/actions.jsonl`'e simüle edilmiş olarak loglanır.

## Acil Durum

- `KILL_SWITCH=true` ortam değişkenini ayarlayarak botu hiçbir dış çağrı
  yapmadan durdurabilirsiniz (FAZ 5).
- Şüpheli davranışta `DRY_RUN=true`'ya geri dönün.

## Proje Durumu

Bu repo şu an **FAZ 0** (ortam doğrulama ve iskelet) aşamasındadır. Sırasıyla
ilerleyen faz planı için `CLAUDE.md`'ye bakın.
