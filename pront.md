# CLAUDE.md — Meta Ads AI Agent

Bu dosya, bu repo üzerinde çalışan Claude Code (veya başka bir ajan) için
projenin tamamını baştan sona, faz faz tamamlaması amacıyla yazılmıştır.
Her faz bir öncekinin üzerine inşa edilir. **Bir fazı bitirmeden bir
sonrakine geçme.** Her fazın sonunda "Kabul Kriterleri" bölümündeki
maddeler karşılanmadan ilerleme.

---

## 0. Proje Misyonu

Facebook/Meta Ads Manager hesabındaki kampanyaları **Marketing API v25.0**
üzerinden okuyan, performans verisini Claude API ile yorumlayıp aksiyon
önerileri üreten, bu önerileri sabit kod-tabanlı güvenlik sınırlarından
(guardrail) geçiren ve ancak öyle uygulayan **otonom** bir reklam optimizasyon
ajanı inşa ediyoruz. Nihai hedef: insan müdahalesi olmadan, önceden
tanımlanmış risk sınırları içinde bütçe/durum optimizasyonu yapabilen,
production'da güvenle çalıştırılabilecek bir sistem.

Bu sistemin ikinci ana yeteneği: hesaba bağlı **Instagram Business
hesabındaki organik gönderileri** kaynak olarak kullanıp, performansı iyi
olan gönderilerden yola çıkarak **yeni reklam creative'leri ve kampanyaları
otomatik oluşturmak** (FAZ 11-12). Bu, mevcut kampanya optimizasyon
yeteneğinden ayrı ama onunla aynı guardrail felsefesini paylaşan bir
modüldür: bot yeni kampanya/reklam *önerebilir ve oluşturabilir*, ama
insan onayı olmadan asla yayına (ACTIVE) alamaz.

## 1. Değişmez Kurallar (Her Fazda Geçerli)

Bunlar müzakere edilemez; hiçbir faz bu kuralları gevşetmek için gerekçe
üretmemeli:

1. **Guardrail katmanı asla bypass edilmez.** Karar motorunun (LLM) çıktısı
   hiçbir zaman doğrudan `action_executor.py`'ye gitmez; her zaman
   `guardrails.py`'den geçer.
2. **DRY_RUN varsayılan olarak `true` kalır.** Bunu `false` yapmak sadece
   Faz 8'de, açık kullanıcı onayıyla ve kademeli olarak yapılır.
3. **Bilinmeyen/uydurulmuş `adset_id` her zaman reddedilir.** LLM
   hallüsinasyonunun production'a sızmasına izin verilmez.
4. **Her aksiyon loglanır** — uygulanan, uygulanmayan, hata alan, guardrail
   tarafından reddedilen: hepsi `logs/actions.jsonl`'e insan tarafından
   okunabilir gerekçesiyle yazılır.
5. **Sırlar (`META_ACCESS_TOKEN`, `ANTHROPIC_API_KEY`) asla commit edilmez.**
   `.env` her zaman `.gitignore`'da olmalı. Sadece `.env.example` commit edilir.
6. **Rate limit hataları sessizce yutulmaz**, backoff ile yeniden denenir ve
   loglanır.
7. **Bir faz içinde harcama yapan (gerçek para etkileyen) hiçbir kod,
   ilgili test/dry-run kanıtı olmadan bir sonraki faza taşınmaz.**
8. **Bot tarafından oluşturulan her yeni kampanya/ad set/reklam her zaman
   `PAUSED` durumunda oluşturulur.** Bot hiçbir zaman kendi oluşturduğu
   yeni bir reklamı otomatik olarak `ACTIVE`'e çekmez — bunu sadece insan
   onayı (manuel Ads Manager'dan veya ayrı bir onay adımından) yapar.
   Bu kural mevcut kampanya bütçe/durum optimizasyonundan (Faz 0-10) tamamen
   ayrıdır ve ondan daha katıdır, çünkü sıfırdan yeni harcama başlatmak
   var olan bir kampanyayı ayarlamaktan daha yüksek risklidir.

## 2. Mevcut Durum (Başlangıç Noktası)

Repo şu an aşağıdaki iskeletle geliyor — bunlar zaten var, sıfırdan yazma,
üzerine inşa et / sertleştir:

```
config.py             — .env okuyucu, guardrail sabitleri
meta_client.py         — Graph API v25.0 ince istemcisi (requests tabanlı)
data_fetcher.py         — aktif ad set performans verisi toplama
decision_engine.py      — Claude API ile JSON aksiyon önerisi üretme
guardrails.py            — bütçe tavanı / max değişim / min spend kontrolü
action_executor.py       — onaylı aksiyonları uygulama (DRY_RUN destekli)
logger.py                — JSONL audit log
main.py                   — scheduler + tek seferlik çalıştırma (--once)
requirements.txt
.env.example
README.md
```

FAZ 11-12'de aşağıdaki yeni dosyalar bu yapıya eklenecek (henüz yok,
sıfırdan yazılacak): `ig_client.py`, `creative_generator.py`,
`campaign_builder.py`, `creative_guardrails.py`.

Her fazda önce ilgili dosyaları oku, mevcut davranışı anla, sonra değişiklik yap.

---

## FAZ 0 — Ortam Doğrulama ve Proje Sağlığı

**Amaç:** Mevcut iskeletin gerçekten çalıştığını doğrulamak, eksik/kırık
noktaları tespit etmek.

**Görevler:**
- [ ] `pip install -r requirements.txt` çalıştır, hata var mı kontrol et.
- [ ] `python -m py_compile` ile tüm `.py` dosyalarını derle.
- [ ] `.env.example`'ı `.env`'e kopyala, sahte/test değerlerle doldur.
- [ ] `config.py` içindeki `Config.validate()` fonksiyonunun eksik değişkenleri
      doğru yakaladığını manuel test et (bilerek bir değeri boş bırakıp çalıştır).
- [ ] `.gitignore` dosyası yoksa oluştur: `.env`, `logs/`, `__pycache__/`,
      `*.pyc`, `.venv/` içermeli.
- [ ] Git reposu başlatılmamışsa `git init`, ilk commit at (`.env` HARİÇ).

**Kabul Kriterleri:**
- Tüm dosyalar hatasız derleniyor.
- `.env` git tarafından takip edilmiyor (`git status` ile doğrula).
- Eksik ortam değişkeninde `Config.validate()` anlamlı hata veriyor.

---

## FAZ 1 — Meta API Katmanının Sertleştirilmesi

**Amaç:** `meta_client.py` ve `data_fetcher.py`'yi gerçek dünya
senaryolarına dayanıklı hale getirmek.

**Görevler:**
- [ ] `meta_client.py`'ye **mock/test modu** ekle: `META_MOCK_MODE=true`
      olduğunda gerçek API'ye gitmeden sabit örnek veri (fixtures) döndürsün.
      Bu, sonraki fazlarda gerçek token olmadan test etmeyi sağlar.
      `fixtures/sample_campaigns.json`, `fixtures/sample_insights.json`
      gibi dosyalar oluştur.
- [ ] Pagination desteği ekle: Graph API `paging.next` alanı varsa
      `get_campaigns` / `get_adsets` bunu takip edip tüm sayfaları birleştirsin.
- [ ] Hata sınıflandırmasını genişlet: auth hatası (code 190) ile rate-limit
      hatasını (code 4/17/32/613) ayrı ele al; auth hatasında **retry yapma**,
      direkt anlamlı mesajla patlat (token'ı yenilemek insan işi).
- [ ] `data_fetcher.py`'de sıfır harcamalı / veri dönmeyen ad set'leri
      sessizce atlarken bunu debug seviyesinde logla (görünürlük için).
- [ ] Timeout ekle (`requests` çağrılarına `timeout=15`).

**Kabul Kriterleri:**
- `META_MOCK_MODE=true` ile `python main.py --once` gerçek token olmadan
  uçtan uca çalışıyor, mock veriyle bir snapshot üretiyor.
- Auth hatası simülasyonunda retry döngüsüne girmiyor.
- Pagination'lı sahte cevapla test edildiğinde tüm sayfalar birleşiyor.

---

## FAZ 2 — Karar Motoru (Decision Engine) Doğrulama ve Sağlamlaştırma

**Amaç:** `decision_engine.py`'nin Claude'dan gelen çıktıyı güvenilir şekilde
işlediğinden emin olmak.

**Görevler:**
- [ ] JSON parse başarısız olduğunda mevcut davranış (boş liste dönmek)
      korunuyor mu doğrula, ayrıca bunu **logla** (şu an sessizce yutuyor —
      en azından stderr'e veya `logs/decision_errors.log`'a yaz).
- [ ] Şema doğrulama ekle: dönen her `action` objesinde `adset_id`,
      `action` (izin verilen değerler: `update_budget`, `pause`, `activate`,
      `no_action`) alanları var mı kontrol et; eksikse o aksiyonu ele.
- [ ] `SYSTEM_PROMPT`'a örnek (few-shot) bir input/output çifti ekle —
      modelin format tutarlılığını artırır.
- [ ] Maliyet kontrolü: `snapshot` çok büyükse (ör. 200+ ad set) tek
      çağrıda göndermek yerine mantıklı bir üst sınırda kırp veya
      batch'lere böl (basit bir ilk versiyon: en yüksek harcamalı ilk
      N ad set'i önceliklendir).
- [ ] Karar motorunun ürettiği her aksiyonun `reason` alanının boş
      olmadığını doğrula (boşsa ele).

**Kabul Kriterleri:**
- Bozuk/eksik JSON döndüren sahte bir Claude cevabıyla test edildiğinde
  sistem çökmeden boş aksiyon listesiyle devam ediyor ve bunu logluyor.
- Şemaya uymayan bir aksiyon (ör. `action: "delete_campaign"`) otomatik
  eleniyor.

---

## FAZ 3 — Guardrail Katmanının Test Edilmesi

**Amaç:** Guardrail'lerin gerçekten "fail closed" davrandığını kanıtlamak.
Bu proje için en kritik faz — burada zaman harca.

**Görevler:**
- [ ] `tests/test_guardrails.py` oluştur (pytest). En az şu senaryoları kapsa:
  - Bilinmeyen `adset_id` içeren aksiyon reddediliyor mu?
  - `MIN_SPEND_BEFORE_ACTION` altındaki ad set'e (pause hariç) aksiyon
    engelleniyor mu?
  - `MAX_BUDGET_CHANGE_PERCENT`'i aşan bir bütçe önerisi doğru şekilde
    kırpılıyor mu (clamp)?
  - Toplam önerilen bütçe `MAX_DAILY_BUDGET_TOTAL`'ı aştığında
    `GuardrailViolation` fırlatılıyor ve **hiçbir aksiyon uygulanmıyor** mu?
  - `MAX_ACTIONS_PER_RUN`'dan fazla aksiyon önerildiğinde fazlası
    kesiliyor mu?
- [ ] `pytest` çalıştır, hepsi geçmeden bu fazı kapatma.
- [ ] Guardrail ihlali durumunda kullanıcıya nasıl bildirim gideceğini
      belirle (şimdilik konsola yazdırmak yeterli, Faz 6'da bildirim
      sistemine bağlanacak).

**Kabul Kriterleri:**
- `pytest tests/test_guardrails.py -v` içindeki tüm testler yeşil.
- Guardrail testleri gerçek API'ye hiç dokunmuyor (tamamen izole, mock veriyle).

---

## FAZ 4 — Action Executor ve Uçtan Uca Dry-Run

**Amaç:** DRY_RUN modunda tüm boru hattının (pipeline) uçtan uca, gerçekçi
mock veriyle sorunsuz çalıştığını kanıtlamak.

**Görevler:**
- [ ] `META_MOCK_MODE=true` + `DRY_RUN=true` ile `python main.py --once`
      çalıştır, `logs/actions.jsonl`'i incele; her satırın anlamlı ve
      okunabilir olduğunu doğrula.
- [ ] `action_executor.py`'ye kısmi başarısızlık senaryosu ekle: 5 aksiyondan
      3'ü başarılı, 2'si hata verirse sistem durmadan devam etmeli ve
      hepsini raporlamalı (mevcut kod bunu zaten yapıyor olmalı — doğrula).
- [ ] Çalıştırma sonunda bir **özet** üret (kaç aksiyon önerildi, kaçı
      guardrail'de elendi, kaçı uygulandı/dry-run'da kaldı, kaçı hata verdi).
      Bunu `main.py` sonunda konsola yazdır.

**Kabul Kriterleri:**
- Tam pipeline (mock veri → Claude → guardrail → executor → log) tek
  komutla, hatasız, gerçek para/gerçek API olmadan uçtan uca çalışıyor.
- Çalıştırma özeti doğru sayıları raporluyor.

---

## FAZ 5 — Zamanlama ve Operasyonel Dayanıklılık

**Amaç:** `main.py`'nin production'da güvenilir şekilde sürekli
çalışabilmesini sağlamak.

**Görevler:**
- [ ] Çalıştırma aralığını `.env` üzerinden yapılandırılabilir yap
      (`RUN_INTERVAL_HOURS`, şu an kodda sabit 4 saat).
- [ ] Bir çalıştırma sırasında exception fırlarsa scheduler'ın çökmemesini,
      hatayı loglayıp bir sonraki çalıştırmayı beklemesini sağla
      (APScheduler job'ı try/except ile sar).
- [ ] Basit bir "kill switch" ekle: `KILL_SWITCH=true` ortam değişkeni
      varsa `run_once()` hiçbir API çağrısı yapmadan hemen çıksın. Bu,
      acil durumda kod deploy etmeden botu durdurabilmek için.
- [ ] Graceful shutdown: `Ctrl+C` / `SIGTERM` geldiğinde yarım kalan bir
      aksiyon uygulaması varsa onu bitirsin, yenisini başlatmasın.

**Kabul Kriterleri:**
- `KILL_SWITCH=true` iken bot hiçbir dış çağrı yapmadan güvenle çıkıyor.
- Kasıtlı olarak `decision_engine.py`'de hata fırlatılınca scheduler
  process'i kill olmuyor, bir sonraki cycle'da normal çalışıyor.

---

## FAZ 6 — Bildirim ve Görünürlük

**Amaç:** İnsan operatörün botun ne yaptığını gerçek zamanlı takip
edebilmesi (özellikle DRY_RUN=false sonrası kritik).

**Görevler:**
- [ ] `notifier.py` oluştur: Slack webhook URL'i (`SLACK_WEBHOOK_URL` env
      değişkeni) varsa her çalıştırma sonunda özet mesajı gönder.
      Yoksa sessizce atla (opsiyonel olmalı, zorunlu bağımlılık yaratma).
- [ ] Guardrail ihlali (`GuardrailViolation`) oluştuğunda bildirim
      **her zaman** gönderilsin (bu, dikkat gerektiren bir durum).
- [ ] Günlük/haftalık özet raporu üretecek ayrı bir script taslağı
      (`reports/weekly_summary.py`): `logs/actions.jsonl`'i okuyup
      toplam uygulanan aksiyon, toplam guardrail reddi, en çok
      değiştirilen ad set'ler gibi metrikleri özetlesin.

**Kabul Kriterleri:**
- Slack webhook olmadan sistem hatasız çalışmaya devam ediyor
  (bildirim opsiyonel bağımlılık).
- Sahte bir guardrail ihlali tetiklendiğinde bildirim fonksiyonu
  çağrılıyor (mock/test ile doğrula).

---

## FAZ 7 — Test Kapsamının Genişletilmesi

**Amaç:** Guardrail testlerinin ötesinde tüm kritik modüllerin
test edilmesi.

**Görevler:**
- [ ] `tests/test_decision_engine.py`: bozuk JSON, eksik alan, şemaya
      uymayan `action` değeri senaryoları.
- [ ] `tests/test_meta_client.py`: mock modunda pagination, rate-limit
      backoff, auth hatası senaryoları.
- [ ] `tests/test_data_fetcher.py`: sıfır ad set, sıfır harcama, eksik
      `purchases` verisi senaryoları.
- [ ] `pytest --cov` ile kapsamı ölç, kritik dosyalarda (guardrails.py,
      action_executor.py) en az %90 satır kapsamı hedefle.
- [ ] CI için basit bir GitHub Actions workflow'u ekle
      (`.github/workflows/test.yml`): push'ta `pytest` çalıştırsın.

**Kabul Kriterleri:**
- `pytest` tüm test dosyalarında yeşil.
- `guardrails.py` ve `action_executor.py` kapsamı ≥ %90.

---

## FAZ 8 — Kademeli Canlıya Alma (Staged Rollout)

**Amaç:** Botu gerçek para harcayan moda **güvenli ve geri dönüşü olan**
adımlarla geçirmek. Bu fazda hız değil temkinlilik önceliklidir.

**Görevler (sırayla, her adımda en az birkaç gün bekle):**
1. [ ] Gerçek Meta hesabına gerçek token ile bağlan, `DRY_RUN=true`,
       `META_MOCK_MODE=false` yap. Birkaç gün çalıştır, `logs/actions.jsonl`'i
       insan olarak incele — bot kararları mantıklı mı?
2. [ ] `MAX_DAILY_BUDGET_TOTAL`'ı gerçek hesabın günlük harcamasının çok
       altında, küçük bir değere sabitle (ör. gerçek bütçenin %5-10'u).
3. [ ] Tek bir düşük riskli kampanya/ad set grubunu botun kapsamına al
       (ör. `data_fetcher.py`'de filtre ekleyerek sadece belirli bir
       kampanya adı/etiketiyle sınırla), geri kalanına dokunmasın.
4. [ ] `DRY_RUN=false` yap, sadece bu sınırlı kapsamda canlıya al.
       Slack bildirimlerini yakından izle.
5. [ ] Sorun yoksa kapsamı kademeli genişlet, `MAX_DAILY_BUDGET_TOTAL`'ı
       kademeli artır.

**Kabul Kriterleri:**
- Her adımda en az X gün (kullanıcı ile netleştirilecek) sorunsuz
  çalıştıktan sonra bir sonraki adıma geçiliyor.
- Herhangi bir beklenmeyen davranışta hemen `KILL_SWITCH=true` veya
  `DRY_RUN=true`'ya geri dönülüyor ve kök neden analiz ediliyor.

**Bu fazda ASLA yapılmayacaklar:**
- Tüm hesabı aynı anda tam otonom moda almak.
- Guardrail sabitlerini "daha hızlı optimize etsin" diye gevşetmek.
- Bildirim/log sistemini devre dışı bırakıp "arka planda" çalıştırmak.

---

## FAZ 9 — Production Sertleştirme

**Amaç:** Uzun süreli, gözetimsiz çalışmaya hazır hale getirmek.

**Görevler:**
- [ ] Sırları ortam değişkeninden değil (mümkünse) bir secret manager'dan
      okuyacak şekilde `config.py`'yi genişlet (opsiyonel, kullanıcının
      altyapısına göre: AWS Secrets Manager / GCP Secret Manager / Vault).
- [ ] Token yenileme/expiry uyarısı: System User token'ının süresi
      dolmaya yaklaştığında (Meta bunu döndürüyorsa) erken uyarı ver.
- [ ] Yapılandırılabilir log rotasyonu (`logs/actions.jsonl` sonsuza kadar
      büyümesin — aylık dosyalara böl veya boyut bazlı rotate et).
- [ ] `README.md`'yi güncelle: production deployment adımları (Docker,
      systemd servisi, ya da bulut zamanlayıcı — kullanıcının tercihine göre).
- [ ] Basit bir health-check endpoint'i veya heartbeat log satırı ekle,
      dış izleme (uptime monitor) botun canlı olup olmadığını anlayabilsin.

**Kabul Kriterleri:**
- Token/secret hiçbir yerde düz metin log'a yazılmıyor (grep ile doğrula).
- `logs/` dizini kontrolsüz büyümüyor.

---

## FAZ 10 — Dokümantasyon ve Devir Teslim

**Amaç:** Projenin, onu yazmamış birinin de güvenle işletebileceği hale
gelmesi.

**Görevler:**
- [ ] `README.md`'yi son haliyle güncelle: kurulum, çalıştırma, guardrail
      mantığının açıklaması, acil durumda ne yapılacağı (kill switch,
      DRY_RUN'a dönüş).
- [ ] `RUNBOOK.md` oluştur: "Bot yanlış bir aksiyon aldı, ne yapmalıyım?",
      "Token süresi doldu, nasıl yenilerim?", "Guardrail sürekli
      reddediyor, nasıl teşhis ederim?" gibi operasyonel senaryolar.
- [ ] Tüm ortam değişkenlerinin güncel ve doğru açıklamalı listesi
      `.env.example`'da.
- [ ] Değişiklik geçmişini `CHANGELOG.md`'de tutmaya başla.

**Kabul Kriterleri:**
- Projeyi hiç görmemiş bir geliştirici, sadece `README.md` + `RUNBOOK.md`
  okuyarak botu DRY_RUN modunda ayağa kaldırabiliyor.

---

---

## FAZ 11 — Instagram Gönderilerinden Veri Toplama ve Creative Üretimi

> Bu faz Faz 4 tamamlandıktan sonra herhangi bir zamanda paralel bir hat
> olarak başlatılabilir; mevcut optimizasyon pipeline'ını (Faz 5-10)
> bloklamaz. Ancak bu fazın çıktısı gerçek bir kampanyaya dönüşmeden önce
> Faz 12'deki guardrail'lerin tamamlanmış olması şarttır.

**Amaç:** Bağlı Instagram Business hesabındaki organik gönderileri
çekmek, içlerinden reklam adayı olabilecekleri seçmek ve bunlardan
reklam creative'i (metin + görsel) üretmek.

**Ön koşul (kullanıcı tarafında):**
- Instagram hesabı bir **Business/Creator** hesabı olmalı ve bağlı bir
  Facebook Page'e bağlanmış olmalı.
- System User token'ına `instagram_basic` ve `pages_read_engagement`
  izinleri eklenmeli (mevcut `ads_management`/`ads_read`'e ek olarak).
- Instagram Business Account ID'si Graph API üzerinden
  `GET /{page-id}?fields=instagram_business_account` ile alınabilir.

**Görevler:**
- [ ] `ig_client.py` oluştur: `MetaClient`'a benzer ince bir istemci.
  - `get_recent_media(ig_user_id, limit=25)` → `GET /{ig-user-id}/media`
    ile `id, caption, media_type, media_url, permalink, timestamp,
    like_count, comments_count` alanlarını çeker.
  - `get_media_insights(media_id)` → `GET /{media-id}/insights` ile
    `reach, engagement, saved` gibi organik performans metriklerini çeker
    (mevcut IG API alan adlarını kullan, deprecated alanlara düşme).
  - Aynı `meta_client.py`'deki gibi rate-limit backoff ve mock modu
    (`IG_MOCK_MODE=true`) uygula — Faz 1'deki desenle tutarlı olsun.
- [ ] Gönderi skorlama mantığı ekle (`ig_client.py` içinde veya ayrı bir
      `post_selector.py`): engagement rate'e göre sırala
      (`(like_count + comments_count) / reach` veya benzeri basit bir
      formül), en iyi performans gösteren ilk N gönderiyi reklam adayı
      olarak işaretle. Çok yeni (yeterli veri toplamamış, ör. <48 saatlik)
      gönderileri ele.
- [ ] `creative_generator.py` oluştur: seçilen her gönderi için Claude'a
      şu görevi ver — gönderinin caption'ını, temasını analiz edip **reklam
      için optimize edilmiş** yeni metin varyasyonları üret (primary text,
      headline, description). Organik caption'ı olduğu gibi reklam metni
      olarak kullanma; ton ve CTA reklam formatına göre farklıdır.
  - Çıktı yine yapılandırılmış JSON olsun (Faz 2'deki `decision_engine.py`
    desenini takip et): `{"media_id", "primary_text", "headline",
    "description", "reasoning"}`.
  - Bozuk/eksik JSON'da Faz 2'deki gibi güvenli şekilde boş dön, asla
    tahmin ederek alan doldurma.
- [ ] Görsel/video varlığının reklamda nasıl kullanılacağına iki seçenek
      tasarla ve `README.md`'de belgele (implementasyonu kullanıcıyla
      netleştirilecek tercihe göre seç):
  - **Seçenek A (düşük risk, önerilen ilk versiyon):** Var olan organik
    gönderiyi olduğu gibi reklam creative'i olarak kullan
    (`object_story_id` = `{page_id}_{post_id}`), sadece yeni metin/CTA
    ekleme yerine mevcut post'u "boost" mantığıyla kullan. Görsel/video
    yeniden yüklenmez, en az teknik risk.
  - **Seçenek B (daha esnek, daha riskli):** Gönderinin medyasını
    `/act_<id>/adimages` veya `/act_<id>/advideos` ile yeniden yükleyip
    yepyeni bir `ad_creative` objesi oluştur, üretilen yeni metinle
    birleştir. Bu, format/crop/metin yerleşimi üzerinde daha fazla kontrol
    verir ama daha fazla API çağrısı ve hata yüzeyi demektir.
  - İlk implementasyon **Seçenek A** ile başlasın; B, Faz 12 stabil
    olduktan sonra ayrı bir alt görev olarak ele alınsın.

**Kabul Kriterleri:**
- `IG_MOCK_MODE=true` ile sahte gönderi verisiyle uçtan uca:
  gönderi çekme → skorlama → creative metni üretme akışı hatasız çalışıyor.
- Üretilen creative önerileri gerçek Meta API'sine hiçbir yazma çağrısı
  yapmıyor (bu faz sadece **öneri üretir**, henüz kampanya oluşturmaz).
- Reklam metni ile organik caption'ın birebir aynı olmadığı doğrulanıyor
  (yani gerçekten "reklama göre optimize etme" adımı işliyor).

---

## FAZ 12 — Otomatik Kampanya/Reklam Oluşturma ve Genişletilmiş Guardrail

**Amaç:** Faz 11'de üretilen creative önerilerini gerçek (ama her zaman
`PAUSED` durumda) kampanya/ad set/reklam objelerine dönüştürmek — ve bunu
mevcut bütçe guardrail'lerinden **ayrı, en az o kadar katı** yeni bir
guardrail katmanıyla korumak.

**Görevler:**
- [ ] `meta_client.py`'ye yeni yazma metodları ekle (mevcut `pause_entity`/
      `update_adset_budget` desenine uygun şekilde):
  - `create_campaign(name, objective, status="PAUSED")`
  - `create_adset(campaign_id, name, daily_budget, targeting, status="PAUSED")`
  - `create_ad_creative(object_story_id veya image_hash+text, ...)`
  - `create_ad(adset_id, creative_id, status="PAUSED")`
  - **Bu dört metodun hiçbiri `status` parametresini `ACTIVE` olarak
    kabul etmemeli** — fonksiyon imzasında `status` sabit `"PAUSED"`
    olsun, dışarıdan override edilemesin. Bu, Değişmez Kural #8'in kod
    seviyesinde zorlanmasıdır.
- [ ] `campaign_builder.py` oluştur: Faz 11'in ürettiği creative
      önerilerini alıp yukarıdaki metodlarla sırayla kampanya → ad set →
      creative → reklam oluşturur. Her adımda hata olursa yarım kalan
      objeleri temizlemeye çalışmaz (silme de riskli bir yazma işlemidir);
      bunun yerine hatayı ve o ana kadar oluşan obje ID'lerini açıkça
      loglar, insan manuel temizleyebilsin.
- [ ] `creative_guardrails.py` oluştur — `guardrails.py`'den ayrı, çünkü
      farklı bir risk sınıfı:
  - `MAX_NEW_CAMPAIGNS_PER_RUN` (öneri: varsayılan 1-3)
  - `MAX_NEW_CAMPAIGNS_PER_DAY` (çoklu run'lar boyunca birikimli sayaç,
    `logs/`'daki geçmiş kayıtlardan hesaplanabilir)
  - `DEFAULT_NEW_ADSET_DAILY_BUDGET` — Claude'un önerdiği bütçeye
    bakılmaksızın, yeni oluşturulan bir ad set'in başlangıç bütçesi bu
    sabit değerin üzerine asla çıkmaz (insan onayından sonra elle
    artırılır).
  - İçerik/politika ön kontrolü: üretilen `primary_text`/`headline`
    içinde yasaklı kelime listesi (basit bir kara liste ile başla —
    sağlık iddiaları, "garantili sonuç" gibi Meta reklam politikasını
    ihlal etme riski yüksek ifadeler) taranır, eşleşirse o creative
    reddedilir ve loglanır.
  - Faz 3'teki gibi: guardrail ihlalinde **hiçbir obje oluşturulmaz**,
    fail-closed.
- [ ] `tests/test_creative_guardrails.py`: Faz 3'teki test desenini takip
      ederek yukarıdaki her sınırın gerçekten uygulandığını doğrula
      (mock/izole, gerçek API'ye dokunmadan).
- [ ] `main.py`'ye (veya ayrı bir `run_creative_pipeline.py`'ye) bu akışı
      mevcut optimizasyon döngüsünden **ayrı, isteğe bağlı** bir komut
      olarak bağla (ör. `python run_creative_pipeline.py --once`) —
      mevcut bütçe optimizasyon döngüsüyle aynı process'te otomatik
      tetiklenmesin, çünkü bu çok daha yüksek riskli bir işlem sınıfı ve
      insan bunu bilinçli olarak çalıştırmalı.
- [ ] `notifier.py`'yi genişlet (Faz 6 varsa): her yeni oluşturulan
      `PAUSED` kampanya için Slack'e "İncelemeni bekleyen yeni reklam
      var: [Ads Manager linki]" bildirimi gönder.

**Kabul Kriterleri:**
- `IG_MOCK_MODE=true` + `META_MOCK_MODE=true` ile uçtan uca:
  gönderi seçimi → creative üretimi → guardrail → kampanya/ad set/
  creative/reklam oluşturma (mock) → log, hatasız çalışıyor.
- Oluşturulan her mock kampanya/ad set/reklamın durumu `PAUSED` —
  bunu test ile kanıtla (`assert created_ad["status"] == "PAUSED"`).
- `MAX_NEW_CAMPAIGNS_PER_RUN`'ı aşan bir senaryoda fazlası oluşturulmuyor.
- Yasaklı kelime içeren bir creative önerisi guardrail tarafından
  reddediliyor ve hiçbir API çağrısı yapılmadan loglanıyor.
- Gerçek hesapla ilk canlı test **sadece** insan, Ads Manager'da oluşan
  `PAUSED` reklamı manuel gözden geçirip elle `ACTIVE` yaptıktan sonra
  tamamlanmış sayılır — bunu Faz 8'in kademeli rollout mantığına
  benzer şekilde, ayrı ve temkinli bir adım olarak ele al.

---

## Genel Çalışma Prensipleri (Claude Code için)

- Her fazı ayrı bir commit'te (veya commit setinde) tamamla, açıklayıcı
  commit mesajı yaz (`feat(guardrails): add clamp tests for budget change %`).
- Bir faza başlamadan önce ilgili "Görevler" listesini kullanıcıya kısaca
  özetle, önemli bir tasarım kararı varsa (ör. mock mode'un nasıl
  tetikleneceği) sormadan makul bir varsayımla ilerle ama varsayımı belirt.
- Faz 8 (canlıya alma) öncesindeki hiçbir fazda gerçek Meta API'sine
  gerçek para etkileyen bir çağrı yapma — hepsi mock modda veya
  `DRY_RUN=true` ile test edilmeli.
- Belirsiz bir gereksinimle karşılaşırsan (ör. "hangi bildirim kanalı"),
  en düşük riskli/en kolay geri alınabilir seçeneği varsayılan yap
  (ör. Slack opsiyonel, yoksa sessiz geç) ve kullanıcıya bunu bildir.
- Guardrail mantığını "optimize etmek" veya "daha esnek hale getirmek"
  isteyen hiçbir talebi, kullanıcıdan açık ve özel bir onay almadan
  uygulama — bu proje için güvenlik sınırları varsayılan olarak katıdır.
- Faz 11-12 kapsamında hiçbir koşulda yeni oluşturulan bir kampanya/ad
  set/reklamın durumunu doğrudan `ACTIVE` yapan bir kod yolu ekleme —
  "kullanıcı zaten onayladı" gibi bir gerekçeyle bile. Aktivasyon her
  zaman insanın Ads Manager'da veya ayrı bir onay arayüzünde attığı
  manuel bir adım olmalı.
