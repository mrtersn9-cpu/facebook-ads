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
approval_queue.py         AUTOMATION_MODE="onayli" iken bekleyen aksiyon kuyruğu
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

## Masaüstü Uygulaması (opsiyonel kolaylık aracı)

CLAUDE.md'deki faz planına ek, isteğe bağlı bir masaüstü arayüzü
(Tkinter — Python ile birlikte gelir, ek kurulum gerektirmez):

```bash
python desktop_app.py
```

- Üstte `DRY_RUN`/`KILL_SWITCH`/`META_MOCK_MODE`/`IG_MOCK_MODE`/
  `CAMPAIGN_OBJECTIVE`/hesap ID durumunu **salt okunur**, renkli gösterir
  (`DRY_RUN=False` kırmızı, `KILL_SWITCH=True` kırmızı) — bunları
  değiştirmek için hâlâ `.env`'yi elle düzenlemeniz gerekir; arayüzden
  guardrail/DRY_RUN bypass edilemez.
- İki düğme mevcut `main.py --once` / `run_creative_pipeline.py --once`
  komutlarını arka planda (ayrı thread'de, arayüz donmadan) alt süreç
  olarak tetikler — yeni bir kod yolu değil, sadece bir kolaylık katmanı.
  `DRY_RUN=False` iken çalıştırmadan önce ekstra bir uyarı diyaloğu çıkar.
- Sekmeler: **Gönderi Seç** (Instagram gönderilerini getirip checkbox'larla
  hangilerine reklam çıkılacağını manuel seçebileceğiniz panel — "Seçili
  Gönderiler İçin Reklam Oluştur" sadece işaretlediklerinizi
  `run_creative_pipeline.py --once --media-ids ...` ile işler, otomatik
  top-N seçimi devre dışı kalır ama guardrail'ler aynen çalışmaya devam
  eder), **Onay Kuyruğu** (bkz. aşağıdaki "Onay Kuyruğu ve Otomasyon Modu"
  bölümü — bekleyen her aksiyonu tek tek "Onayla"/"Reddet" ile işleyebilirsiniz),
  son çalıştırma çıktısı, `logs/actions.jsonl` kayıtları, 7 günlük
  özet. "Yenile" düğmesiyle güncellenir.

Tarayıcı tabanlı bir alternatif isterseniz `web_ui.py` (Flask, sadece
localhost'ta dinler) de repoda mevcut — aynı salt-okunur/guardrail-bypass-yok
prensipleriyle çalışır, ama varsayılan olarak masaüstü uygulaması önerilir.

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

## Kampanya Hedefi (Awareness vs. Sales)

`CAMPAIGN_OBJECTIVE` (varsayılan `awareness`) karar motorunun ad set'leri
nasıl değerlendireceğini belirler:

- **`awareness`** (varsayılan): Hesap bilinirlik/reach odaklıdır. Karar
  motoru düşük/sıfır `purchases` yüzünden asla `pause` önermez; bunun
  yerine `reach`, `impressions`, `frequency` (reklam yorgunluğu) ve `cpm`
  metriklerine bakar. `data_fetcher.py` bu metrikleri her snapshot satırına
  ekler.
- **`sales`**: Karar motoru satış/dönüşüm verimliliğine (purchases, ROAS)
  göre karar verir — FAZ 0-7'de yazılan orijinal davranış.

Farklı hesapların/kapsamların farklı hedefleri olabilir; şu an tek bir
global ayar olarak uygulanıyor (per-kampanya override yok).

`awareness` modunda karar motoru her ad set'i şu sınıflandırmayla
değerlendirir (sistem promptuna gömülü, `decision_engine.py`):

- 🟢 **SAĞLIKLI**: engagement rate hesap ortalamasının üzerinde VEYA CPM
  ortalamanın altında, frequency < 3.5, ≥1000 impression.
- 🟡 **İZLENMELİ**: <1000 impression veya yetersiz veri → sadece
  `no_action` önerilir (istatistiksel olarak anlamlı değil).
- 🔴 **ZAYIF**: engagement ortalamanın ~%40+ altında VE ≥1000 impression,
  YA DA frequency ≥3.5 (reklam yorgunluğu), YA DA CPM ortalamanın 2 katından
  fazla.

🔴 ZAYIF bir ad set için karar motoru direkt `pause` önermez; her ad set'e
eklenen `recent_history` (son `logs/actions.jsonl` kayıtlarının özeti,
`data_fetcher.py`'de üretilir) alanına bakarak kademeli ilerler: önce
bütçe %50 azaltma önerilir, sadece daha önce (5+ gün önce) zaten bir
bütçe kesintisi yapılmış VE hâlâ ZAYIF ise `pause` önerilir.

`BRAND_CONTEXT` (opsiyonel, boş bırakılabilir) serbest metin bir env
değişkenidir; ayarlanırsa karar motorunun sistem promptuna eklenir — bu,
aracı belirli bir markanın sesi/hedef kitlesi/ton kısıtlarına göre (ör.
"abartılı iddialardan kaçın", "18-45 yaş ebeveyn kitlesi") özelleştirmenizi
sağlar, ama araç genel olarak marka-agnostik kalır.

## Onay Kuyruğu ve Otomasyon Modu

`AUTOMATION_MODE` (varsayılan `"onayli"`) guardrail'den geçmiş bir
aksiyonun **hemen mi uygulanacağını yoksa önce insan onayı mı bekleyeceğini**
belirler — bu, `DRY_RUN`'dan tamamen ayrı bir güvenlik katmanıdır:

- **`onayli`** (varsayılan, güvenli): Guardrail'i geçen her aksiyon
  doğrudan uygulanmaz; `logs/approval_queue.jsonl`'e eklenir ve
  `queued_for_approval` olarak loglanır. Bekleyen aksiyonları görmek ve
  onaylamak/reddetmek için masaüstü uygulamasındaki **"Onay Kuyruğu"**
  sekmesini kullanın — "Onayla" dediğinizde aksiyon `action_executor`'a
  gider ve (DRY_RUN ayarına göre) gerçek uygulanır veya simüle edilir;
  "Reddet" dediğinizde hiçbir API çağrısı yapılmadan `rejected` olarak loglanır.
- **`tam_otomatik`**: Guardrail'i geçen aksiyonlar onay beklemeden direkt
  `action_executor`'a gider (FAZ 0-10'un orijinal davranışı).

> **Önemli:** `AUTOMATION_MODE` ayarlanmamışsa varsayılan `"onayli"`dır.
> Daha önce doğrudan uygulama (direkt `DRY_RUN=false`, onay katmanı yok)
> ile çalışıyorsanız, bu davranışı korumak için `.env`'e
> `AUTOMATION_MODE=tam_otomatik` eklemeniz gerekir — aksi halde bir sonraki
> çalıştırmada hiçbir aksiyon otomatik uygulanmaz, hepsi onay kuyruğuna
> düşer.

Karar motorunun ürettiği her aksiyona ayrıca bir `guven_skoru`
(yüksek/orta/düşük) eklenir — bu guardrail'i **geçirmez/geçirmez**
şeklinde kullanılmaz (programatik bir eşik değildir), sadece onay
kuyruğunda insan gözden geçirene bilgi amaçlı gösterilir.

## Kapsamı Sınırlama

`SCOPE_CAMPAIGN_NAME_FILTER` ayarlanırsa, bot sadece adı bu alt diziyi
içeren kampanyalardaki ad set'lerle ilgilenir. Boşsa hesaptaki tüm aktif
ad set'ler kapsam dahilindedir. Bu, kademeli canlıya alma sırasında botun
etkisini tek bir düşük riskli kampanyaya sınırlamak için kullanılır.

## Test

```bash
pytest                                                                     # tüm testler
pytest --cov=guardrails --cov=action_executor --cov=creative_guardrails    # kritik dosyalarda kapsam
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
  tanesini seçer. `IG_ONLY_VIDEO_POSTS=true` ayarlanırsa resim gönderiler
  tamamen elenir, sadece video/Reels içerik (`media_type == "VIDEO"`)
  reklam adayı olarak değerlendirilir.
- `creative_generator.py` her seçilen gönderi için Claude'dan reklama
  optimize edilmiş yeni metin ister; organik caption'ın birebir aynısı
  veya şemaya uymayan bir cevap gelirse o gönderi için `None` döner —
  hiçbir alan tahmin edilerek doldurulmaz.
- Bu faz gerçek Meta API'sine **hiçbir yazma çağrısı yapmaz**; sadece
  creative önerisi üretir.

**Medyanın reklamda kullanılması için iki seçenek** vardı; **Seçenek A**
implementasyonu FAZ 12'de yapıldı, canlı hesapta test edilerek iki alt
yola ayrıldı (bkz. aşağıdaki "gerçek Meta API gereksinimleri"):

- **Seçenek A (düşük risk, uygulanan bu):** Var olan organik gönderiyi
  olduğu gibi reklam creative'i olarak kullanmak ("boost" mantığı) —
  görsel/video yeniden yüklenmez. **Resim/Feed içerik** için
  `source_instagram_media_id` (doğrudan IG medya id'si) kullanılır.
  **Video/Reels içerik** için bu alan tek başına yetmiyor — Sayfa
  feed'inden zaman damgasıyla eşleşen gerçek Facebook post id'si bulunup
  `object_story_id` (`{page_id}_{facebook_post_id}`) ile kullanılıyor
  (`meta_client.find_page_post_id_for_timestamp`). Eşleşme bulunamazsa
  (gönderi Facebook'a çapraz paylaşılmamışsa) `source_instagram_media_id`'ye
  geri dönülür ve muhtemelen Meta hata verir — bu durumda gönderiyi
  Facebook Sayfası'na da paylaşmanız gerekir.
- **Seçenek B (daha esnek, daha riskli, uygulanmadı):** Medyayı
  `/act_<id>/adimages` veya `/act_<id>/advideos` ile yeniden yükleyip
  sıfırdan bir `ad_creative` oluşturmak — daha fazla kontrol verir ama daha
  fazla API çağrısı ve hata yüzeyi demektir. Ayrı bir alt görev olarak ele
  alınabilir.

### Kampanya/Reklam Oluşturma (FAZ 12)

```
creative_guardrails.py    Faz 11 önerileri için AYRI, en az o kadar katı guardrail
campaign_builder.py        Kampanya → ad set → creative → reklam zincirini kurar
run_creative_pipeline.py   Ayrı, isteğe bağlı komut: python run_creative_pipeline.py --once
```

- `meta_client.py`'deki `create_campaign`/`create_adset`/`create_ad_creative`/
  `create_ad` metotlarının **hiçbirinde `status` parametresi yoktur** —
  `"PAUSED"` payload'a sabit yazılır, dışarıdan hiçbir şekilde override
  edilemez (Değişmez Kural #8'in kod seviyesinde zorlanması; `status="ACTIVE"`
  geçmeye çalışmak `TypeError` ile sonuçlanır).
- `creative_guardrails.py`, `guardrails.py`'den bağımsız bir katmandır:
  - `MAX_NEW_CAMPAIGNS_PER_RUN` (varsayılan 1) ve `MAX_NEW_CAMPAIGNS_PER_DAY`
    (varsayılan 3, `logs/actions.jsonl`'den birikimli sayılır) aşılırsa
    fazlalık reddedilir; günlük limit zaten dolmuşsa hiçbir creative
    onaylanmaz (fail-closed, `CreativeGuardrailViolation`).
  - Yasaklı ifade listesi (`primary_text`/`headline`) taranır; eşleşen
    creative hiçbir API çağrısı yapılmadan reddedilir.
  - Yeni bir ad set'in başlangıç bütçesi her zaman
    `DEFAULT_NEW_ADSET_DAILY_BUDGET` sabitidir — Claude'un önerisi hiç
    sorulmaz/dikkate alınmaz.
- `campaign_builder.py` bir zincirde (kampanya→ad set→creative→reklam)
  hata olursa yarım kalan objeleri silmeye ÇALIŞMAZ (silme de riskli bir
  yazma işlemidir); hatayı ve o ana kadar oluşan obje id'lerini loglar,
  insan manuel temizler. Bir creative'in zinciri başarısız olsa bile
  diğer creative'ler işlenmeye devam eder.
- `run_creative_pipeline.py --once`, ana `main.py` optimizasyon
  döngüsünden **ayrı bir komuttur** ve onunla aynı process'te otomatik
  tetiklenmez — insan bunu bilinçli olarak çalıştırmalıdır.
- Her yeni `PAUSED` kampanya için (Slack ayarlıysa) "incelemeni bekliyor"
  bildirimi + Ads Manager linki gönderilir.

**Gerçek hesapla canlı test sırasında bulunan Meta API gereksinimleri**
(hepsi `meta_client.py`'ye eklendi, hiçbiri CLAUDE.md'nin orijinal
planında yoktu — Meta'nın kendi platform kısıtlamaları):
- `create_campaign`: `special_ad_categories` (varsayılan `["NONE"]`) ve
  `is_adset_budget_sharing_enabled=False` (bütçe kampanya değil ad set
  seviyesinde yönetildiği için) zorunlu.
- `create_adset`: `optimization_goal`, `billing_event`, `bid_strategy`
  (varsayılan `LOWEST_COST_WITHOUT_CAP`) zorunlu; hesabın para biriminde
  bir minimum günlük bütçe eşiği var (`DEFAULT_NEW_ADSET_DAILY_BUDGET`'ı
  buna göre ayarlayın — TL hesaplarda ~₺47+ gerekebiliyor).
  "Mesaja yönlendir" reklamları için `destination_type="INSTAGRAM_DIRECT"`
  + `optimization_goal="CONVERSATIONS"` kullanılır.
- `create_ad_creative`: mesaj CTA'sı için `call_to_action_type`
  `"INSTAGRAM_MESSAGE"` olmalı (`"MESSAGE_PAGE"` sadece Messenger/Facebook
  için geçerli, Instagram'da desteklenmiyor) ve `call_to_action_link`
  olarak `https://ig.me/m/<IG_USERNAME>` deep-link'i gerekiyor.
- **Reels için Facebook Sayfası eşleştirmesi:** `source_instagram_media_id`
  Reels'lerde genelde "Instagram Videosunun Facebook'a Yüklenmesi
  Zorunludur" hatası veriyor, gönderi Sayfa'ya çapraz paylaşılmış olsa
  bile. Çözüm `object_story_id` + Sayfa feed'inden zaman damgasıyla
  bulunan gerçek Facebook post id'si (yukarıya bakın) — bunun çalışması
  için gönderinin gerçekten Facebook'a çapraz paylaşılmış olması gerekir.
  `instagram_actor_id` alanı da denendi ama `source_instagram_media_id`
  ile birlikte kullanıldığında "geçerli bir Instagram hesap ID'si değil"
  hatasına yol açtığından kaldırıldı.
- **Instagram hesabının reklam hesabına ayrı yetkilendirilmesi gerekir:**
  Instagram hesabının bir Facebook Sayfası'na bağlı olması yetmez —
  Business Settings → Hesaplar → Instagram Hesapları → ilgili hesap →
  **"Bağlı Varlıklar"** sekmesinden reklam hesabına da açıkça bağlanmalı
  (`act_<id>/instagram_accounts` API'sinden doğrulanabilir). Bu adım
  atlanırsa hem `object_story_id` hem `source_instagram_media_id` yolları
  başarısız olur.
- Meta App'in **Live mode**'da olması gerekir (Development mode'daki
  uygulamalar başkalarının içeriğinden reklam creative'i oluşturamaz) —
  bunun için de geçerli bir Gizlilik Politikası URL'si (App Settings ->
  Basic) şart.
- Hesap/uygulama tarafında bir yetkilendirme değişikliği (Live mode'a
  geçiş, Instagram-reklam hesabı bağlantısı) yapıldıktan sonra **token'ı
  yenilemek gerekebilir** — mevcut token bazen eski yetkilendirme
  durumunu önbellekte tutuyor.
- **Gerçek hesapla ilk canlı deneme sadece insan, Ads Manager'da oluşan
  `PAUSED` reklamı manuel gözden geçirip elle `ACTIVE` yaptıktan sonra**
  tamamlanmış sayılır (FAZ 8'in kademeli rollout mantığına benzer şekilde).

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

FAZ 0–12'nin tamamı tamamlandı: iskelet, mock/pagination/hata
sınıflandırması, karar motoru şema doğrulama, guardrail test kapsamı,
dry-run pipeline, scheduler dayanıklılığı, bildirimler, genişletilmiş test
kapsamı, production sertleştirme (log rotasyonu, heartbeat, token expiry
uyarısı), Instagram gönderi/creative üretim akışı ve guardrail'li otomatik
kampanya oluşturma (her zaman `PAUSED`). Kademeli canlıya alma (FAZ 8),
gerçek hesapla ve günler süren insan gözetimiyle yapılan bir süreçtir ve bu
repodaki otomasyonun kapsamı dışındadır — sadece ona hazırlık
(`SCOPE_CAMPAIGN_NAME_FILTER`) eklenmiştir; gerçek hesapla ilk canlı
kampanya/reklam denemesi de aynı şekilde insanın Ads Manager'da elle
`ACTIVE` yapmasını bekler. Detaylar için `CLAUDE.md`'ye bakın.
