# Meta Ads AI Agent

Facebook/Meta Ads Manager kampanyalarını Marketing API v25.0 üzerinden okuyan,
performansı Claude API ile yorumlayıp aksiyon önerileri üreten, bu önerileri
sabit kod-tabanlı guardrail'lerden geçiren ve ancak öyle uygulayan bir reklam
optimizasyon ajanı. Faz faz geliştirme planı için [CLAUDE.md](CLAUDE.md)
dosyasına bakın; operasyonel senaryolar (bot yanlış aksiyon aldı, token
yenileme, vb.) için [RUNBOOK.md](RUNBOOK.md)'ye bakın.

## Mimari

```
config.py            .env okuyucu, guardrail sabitleri, tek gerçek kaynak
meta_client.py        Graph API v25.0 istemcisi (mock mod, pagination,
                       auth/rate-limit sınıflandırması, retry/backoff)
data_fetcher.py        Aktif ad set performans snapshot'ı (kapsam filtresi ile)
decision_engine.py      Claude API ile JSON aksiyon önerisi + şema doğrulama
guardrails.py            Bütçe tavanı / max değişim / min spend / fail-closed
action_executor.py       Onaylı aksiyonları uygular (DRY_RUN destekli)
notifier.py               Opsiyonel Slack webhook bildirimi
logger.py                 Rotasyonlu JSONL audit log (logs/actions.jsonl)
main.py                    Scheduler + tek seferlik çalıştırma (--once)
reports/weekly_summary.py  logs/actions.jsonl'den özet rapor
```

Veri akışı: `data_fetcher` → `decision_engine` → `guardrails` →
`action_executor`. Karar motorunun (LLM) çıktısı **hiçbir zaman** doğrudan
`action_executor`'a gitmez; her zaman `guardrails.py`'den geçer.

## Kurulum

```bash
pip install -r requirements.txt
cp .env.example .env
# .env dosyasını gerçek (veya test) değerlerle doldurun
```

## Çalıştırma

```bash
python main.py --once   # boru hattını bir kez çalıştır ve çık
python main.py          # RUN_INTERVAL_HOURS aralığıyla sürekli çalıştır
```

Gerçek Meta hesabı/token'ı olmadan denemek için `.env`'de
`META_MOCK_MODE=true` ayarlayın — bu durumda `fixtures/` altındaki sahte
kampanya/ad set/insight verisiyle çalışır. `ANTHROPIC_API_KEY` her zaman
gerekir (Claude çağrıları mock'lanmaz; bunlar gerçek ama ucuz API çağrılarıdır).

## Guardrail Mantığı

Karar motorunun (Claude) ürettiği her aksiyon önerisi, uygulanmadan önce
`guardrails.py` içindeki sabit kod-tabanlı kontrollerden geçer:

- Bilinmeyen/uydurulmuş `adset_id` içeren aksiyonlar reddedilir.
- `reason` alanı boş olan veya izin verilen aksiyon listesinde olmayan
  (`update_budget`/`pause`/`activate`/`no_action` dışındaki) aksiyonlar reddedilir.
- `MIN_SPEND_BEFORE_ACTION` altındaki ad set'lere (pause hariç) aksiyon uygulanmaz.
- Bütçe değişiklikleri `MAX_BUDGET_CHANGE_PERCENT` ile sınırlanır (clamp).
- Toplam önerilen günlük bütçe `MAX_DAILY_BUDGET_TOTAL`'ı aşarsa, o run için
  **hiçbir aksiyon uygulanmaz** (fail-closed) ve Slack'e (varsa) her zaman
  bildirim gider.
- Bir run'da en fazla `MAX_ACTIONS_PER_RUN` aksiyon uygulanır, fazlası atlanır.

`DRY_RUN=true` iken hiçbir gerçek API yazma çağrısı yapılmaz; aksiyonlar
sadece `logs/actions.jsonl`'e simüle edilmiş olarak loglanır. `DRY_RUN`
varsayılan olarak `true`'dur ve bunu değiştirmek kademeli, dikkatli bir
süreç gerektirir (bkz. CLAUDE.md FAZ 8).

## Kapsamı Sınırlama

`SCOPE_CAMPAIGN_NAME_FILTER` ayarlanırsa, bot sadece adı bu alt diziyi
içeren kampanyalardaki ad set'lerle ilgilenir. Boşsa hesaptaki tüm aktif
ad set'ler kapsam dahilindedir. Bu, kademeli canlıya alma sırasında botun
etkisini tek bir düşük riskli kampanyaya sınırlamak için kullanılır.

## Test

```bash
pytest                                            # tüm testler
pytest --cov=guardrails --cov=action_executor     # kritik dosyalarda kapsam
```

Testler tamamen izole çalışır — gerçek Meta/Anthropic/Slack API'lerine hiç
dokunmaz, `requests`/`anthropic` çağrıları monkeypatch ile sahtelenir.

## Bildirimler

`SLACK_WEBHOOK_URL` ayarlanırsa her run sonunda özet mesajı ve her guardrail
ihlalinde (her zaman) uyarı gönderilir. Ayarlı değilse sistem sessizce bu
adımı atlar — Slack zorunlu bir bağımlılık değildir.

## Instagram Creative Pipeline (FAZ 11-12)

Ana kampanya optimizasyon döngüsünden tamamen ayrı, isteğe bağlı ikinci bir
akış: bağlı Instagram Business hesabındaki organik gönderileri kaynak
alıp yeni reklam creative'leri üretir/oluşturur.

```
ig_client.py           IG Graph API istemcisi (IG_MOCK_MODE destekli, salt okunur)
post_selector.py         Engagement rate'e göre gönderi skorlama/seçme
creative_generator.py     Claude ile reklam metni üretimi (organik caption ≠ reklam metni)
```

- **Ön koşul:** IG hesabı Business/Creator olmalı ve bir Facebook Page'e
  bağlı olmalı; token'a `instagram_basic` + `pages_read_engagement` izinleri
  eklenmeli.
- `ig_client.py` sadece OKUMA yapar — hiçbir yazma uç noktası içermez.
- `post_selector.select_top_posts()`, `IG_MIN_POST_AGE_HOURS`'tan (varsayılan
  48 saat) daha yeni gönderileri eler (yeterli veri toplamamış olabilirler)
  ve `(like+comment)/reach` engagement rate'ine göre en iyi `IG_TOP_N_POSTS`
  tanesini seçer.
- `creative_generator.py` her seçilen gönderi için Claude'dan reklama
  optimize edilmiş yeni metin ister; organik caption'ın birebir aynısı
  veya şemaya uymayan bir cevap gelirse o gönderi için `None` döner —
  hiçbir alan tahmin edilerek doldurulmaz.
- Bu faz gerçek Meta API'sine **hiçbir yazma çağrısı yapmaz**; sadece
  creative önerisi üretir.

**Medyanın reklamda kullanılması için iki seçenek** (FAZ 12'de değerlendirilecek):

- **Seçenek A (düşük risk, ilk implementasyon bu):** Var olan organik
  gönderiyi `object_story_id` ile olduğu gibi reklam creative'i olarak
  kullanmak ("boost" mantığı) — görsel/video yeniden yüklenmez, en az
  teknik risk.
- **Seçenek B (daha esnek, daha riskli):** Medyayı `/act_<id>/adimages`
  veya `/act_<id>/advideos` ile yeniden yükleyip sıfırdan bir `ad_creative`
  oluşturmak — daha fazla kontrol verir ama daha fazla API çağrısı ve hata
  yüzeyi demektir. Faz 12 stabil olduktan sonra ayrı bir alt görev olarak
  ele alınacaktır.

## Acil Durum

- `KILL_SWITCH=true` ortam değişkenini ayarlayarak botu hiçbir dış çağrı
  yapmadan durdurabilirsiniz.
- Şüpheli davranışta `DRY_RUN=true`'ya geri dönün.
- Detaylı senaryolar için [RUNBOOK.md](RUNBOOK.md)'ye bakın.

## Production Deployment

Bot herhangi bir sürekli çalışan Python process ortamında (systemd servisi,
Docker container, ya da bulut zamanlayıcı) çalıştırılabilir; belirli bir
platforma bağımlılığı yoktur. Asgari gereksinimler:

- `python main.py` sürekli ayakta tutulmalı (crash olursa yeniden başlatılmalı
  — ör. `systemd` `Restart=on-failure` veya container orchestrator'ın kendi
  restart policy'si).
- `logs/` dizini kalıcı bir disk üzerinde olmalı (log rotasyonu dosya
  sayısını sınırlar ama diskin kendisi kalıcı olmalı).
- `.env` dosyası (veya eşdeğer ortam değişkenleri) process'e güvenli şekilde
  sağlanmalı; asla imaja/repoya gömülmemeli.
- Dış bir uptime monitor, `logs/actions.jsonl`'deki (veya stdout'taki)
  periyodik `heartbeat: run_once başlıyor` satırlarını takip ederek
  process'in canlı olduğunu doğrulayabilir.

## Proje Durumu

FAZ 0–9 tamamlandı: iskelet, mock/pagination/hata sınıflandırması, karar
motoru şema doğrulama, guardrail test kapsamı, dry-run pipeline, scheduler
dayanıklılığı, bildirimler, genişletilmiş test kapsamı ve production
sertleştirme (log rotasyonu, heartbeat, token expiry uyarısı). Kademeli
canlıya alma (FAZ 8) insan gözetiminde, gerçek hesapla, günler süren bir
süreçtir ve bu repodaki otomasyonun kapsamı dışındadır — sadece ona hazırlık
(`SCOPE_CAMPAIGN_NAME_FILTER`) eklenmiştir. Detaylar için `CLAUDE.md`'ye
bakın.
