# Changelog

Bu proje CLAUDE.md'deki faz planını takip eder. Her giriş ilgili fazın
kısa özetidir; ayrıntılar için commit geçmişine bakın.

## FAZ 0 — Ortam doğrulama ve iskelet
İlk proje iskeleti: `config.py`, `meta_client.py`, `data_fetcher.py`,
`decision_engine.py`, `guardrails.py`, `action_executor.py`, `logger.py`,
`main.py`. `.gitignore`, `.env.example`, temel `README.md`.

## FAZ 1 — Meta API katmanının sertleştirilmesi
`META_MOCK_MODE` (fixtures ile), `paging.next` takibi, auth (code 190,
retry yok) ve rate-limit (code 4/17/32/613, backoff ile retry) hata
sınıflandırması. `data_fetcher.py`'de atlanan (sıfır harcama/veri yok)
ad set'ler için debug log.

## FAZ 2 — Karar motoru sağlamlaştırma
Bozuk/eksik JSON cevapları `logs/decision_errors.log`'a loglanıyor. Şema
doğrulama (adset_id, izin verilen action, boş olmayan reason). Few-shot
örnek eklendi. 200+ ad set'lik snapshot'lar en yüksek harcamalı ilk 200'e
kırpılıyor.

## FAZ 3 — Guardrail testleri
`tests/test_guardrails.py` fail-closed davranışı kanıtlıyor. Bu süreçte
gerçek bir birim hatası bulundu ve düzeltildi: `daily_budget` alanı Graph
API'den kuruş/cent cinsinden geliyordu ama `action_executor` bunu ana para
birimiymiş gibi tekrar 100 ile çarpıyordu (100x aşırı harcama riski).

## FAZ 4 — Action executor ve uçtan uca dry-run
`tests/test_action_executor.py`: DRY_RUN modunda gerçek client'a hiç
dokunulmadığı, kısmi başarısızlıklarda (5 aksiyondan 2'si hatalı) sistemin
durmadan devam edip hepsini logladığı kanıtlandı. Gerçek `main.run_once()`
uçtan uca (mock Meta verisi + guardrail + dry-run executor) manuel olarak
doğrulandı.

## FAZ 5 — Zamanlama ve operasyonel dayanıklılık
`KILL_SWITCH` — hiçbir dış çağrı yapmadan anında çıkış. Scheduler döngüsü
artık `_safe_run_once()` ile sarmalanıyor; bir run'daki hata scheduler
process'ini öldürmüyor. `SIGINT`/`SIGTERM` mevcut aksiyonu bitirip yenisini
başlatmıyor (`action_executor.install_signal_handlers`).

## FAZ 6 — Bildirim ve görünürlük
`notifier.py`: opsiyonel Slack webhook, her run sonunda özet ve her
guardrail ihlalinde (her zaman) bildirim. `reports/weekly_summary.py`
taslağı.

## FAZ 7 — Test kapsamının genişletilmesi
`tests/test_data_fetcher.py` eklendi. `pytest-cov` ile `guardrails.py` ve
`action_executor.py` %100 satır kapsamına getirildi (eksik kalan
sinyal-handler satırları için doğrudan test eklendi).
`.github/workflows/test.yml` her push/PR'da testleri çalıştırıyor.

## FAZ 8 — Kademeli canlıya alma (hazırlık)
Gerçek hesap/token/günler süren insan gözetimi gerektiren asıl rollout bu
ortamda gerçekleştirilemez ve gerçekleştirilmemiştir. Hazırlık olarak
`SCOPE_CAMPAIGN_NAME_FILTER` eklendi — botun etkisini tek bir kampanyaya
sınırlamak için.

## FAZ 9 — Production sertleştirme
`logs/actions.jsonl` artık boyut bazlı rotasyona sahip
(`ACTIONS_LOG_MAX_BYTES`/`ACTIONS_LOG_BACKUP_COUNT`). Her run'da heartbeat
logu. `meta_client.check_token_expiry()` token süresine
(`TOKEN_EXPIRY_WARN_DAYS`) yaklaşınca erken uyarı veriyor. Secret manager
entegrasyonu bilinçli olarak atlandı (opsiyonel, altyapıya bağımlı); grep
ile hiçbir token/secret'ın log satırına yazılmadığı doğrulandı.

## FAZ 10 — Dokümantasyon
`README.md` son haline getirildi (mimari, kurulum, guardrail mantığı,
production deployment notları). `RUNBOOK.md` eklendi (yanlış aksiyon, token
yenileme, guardrail teşhisi, heartbeat kontrolü senaryoları). Bu
`CHANGELOG.md` başlatıldı.

## FAZ 11 — Instagram gönderi toplama ve creative üretimi
`ig_client.py` (salt okunur, `IG_MOCK_MODE` destekli), `post_selector.py`
(engagement rate skorlama + minimum yaş filtresi), `creative_generator.py`
(Claude ile reklam metni üretimi; organik caption'ın birebir aynısı veya
şemaya uymayan cevaplar `None` olarak elenir). Bu faz gerçek Meta API'sine
hiçbir yazma çağrısı yapmaz — sadece öneri üretir. `IG_MOCK_MODE=true` ile
uçtan uca (Anthropic çağrısı sahtelenerek) doğrulandı.

## FAZ 12 — Otomatik kampanya/reklam oluşturma
`meta_client.py`'ye `create_campaign`/`create_adset`/`create_ad_creative`/
`create_ad` eklendi — hiçbirinde `status` parametresi yok, `"PAUSED"` payload'a
sabit yazılıyor (test: `status="ACTIVE"` geçmeye çalışmak `TypeError`
veriyor). `creative_guardrails.py`: günlük/run başına kampanya limiti
(birikimli olarak `logs/actions.jsonl`'den sayılıyor), yasaklı ifade
taraması, sabit varsayılan ad set bütçesi — hepsi fail-closed.
`campaign_builder.py` bir zincirde hata olursa temizlik denemeden o ana
kadarki obje id'lerini loglar; farklı creative'lerin zincirleri
birbirinden bağımsız işlenir. `run_creative_pipeline.py --once`, ana
optimizasyon döngüsünden ayrı, isteğe bağlı bir komut. Uçtan uca
doğrulandı: 4 aday gönderiden 4 creative üretildi, `MAX_NEW_CAMPAIGNS_PER_RUN=1`
doğru şekilde sadece en yüksek engagement'lı olanı geçirdi, diğer 3'ü
API'ye hiç dokunmadan reddetti, geçen creative için tam `PAUSED`
kampanya→ad set→creative→reklam zinciri oluştu ve loglandı.

Gerçek hesapla ilk canlı deneme, FAZ 8'deki gibi, sadece insanın Ads
Manager'da oluşan `PAUSED` reklamı elle `ACTIVE` yapmasıyla tamamlanmış
sayılır — bu repodaki otomasyon bunu hiçbir koşulda kendisi yapmaz.

## FAZ 8 canlı deneme — kampanya hedefi düzeltmesi (2026-07-02)
Gerçek hesapla (`DRY_RUN=true`, `META_MOCK_MODE=false`) ilk çalıştırmada
bot, hiç satış olmayan bir ad set'i "1772.69 harcamaya rağmen hiç satış
yok" gerekçesiyle `pause` önerdi. Kullanıcı bu hesabın satış değil
**bilinirlik (awareness)** odaklı olduğunu belirtti — düşük/sıfır satış bu
tip hesap için normaldir ve tek başına pause gerekçesi olamaz.

Eklendi: `Config.CAMPAIGN_OBJECTIVE` (`awareness` | `sales`, varsayılan
`awareness`). `data_fetcher.py` artık her snapshot satırına `impressions`,
`reach`, `frequency`, `cpm` ekliyor (`meta_client.get_insights` bu alanları
da çekiyor). `decision_engine.py`'nin sistem promptu `awareness` modunda
Claude'a satış yokluğuna göre asla pause önermemesini, bunun yerine
reach/frequency/CPM'e bakmasını söylüyor.

Gerçek hesapla doğrulandı: aynı ad set için bir sonraki çalıştırmada bot
`no_action` önerdi (satış eksikliğine dayalı pause önerisi kayboldu).
