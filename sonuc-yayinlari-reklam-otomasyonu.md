# Sonuç Yayınları — Claude Tabanlı Tam Otomasyon Reklam Yönetim Sistemi

Instagram sayfanızı inceledim: **@sonuc_yayinlari** — 47K takipçi, 1.300+ paylaşım, YKS/TYT-AYT sınavlarına hazırlık kitapları satan bir eğitim yayınevi. İçerik ağırlıklı olarak sınav teknikleri, kitap setleri, çekiliş/hediye postları ve öğrenci başarı hikayelerinden oluşuyor. Bu, aşağıdaki sistem promptunun "marka sesi" kısmına doğrudan işlendi.

Aşağıda iki ana parça var:
1. **Claude için sistem promptu** (ajanın "beyni" — karar verme mantığı)
2. **Python mimarisi** (ajanı gerçek dünyaya bağlayan iskelet: Meta Ads API, zamanlayıcı, veritabanı, arayüz)

---

## ⚠️ Önce okunması gereken kritik nokta

"Tam otomasyon" isteğinizi anlıyorum, ama gerçek para harcayan bir sistemde **sınırsız otonomi riskli**dir — bir API hatası, veri anomalisi veya Claude'un yanlış yorumladığı bir metrik, bütçeyi birkaç saatte tüketebilir. Bu yüzden mimariye şunları gömdüm:

- **Sert bütçe tavanları** (kod seviyesinde, Claude'un kararından bağımsız)
- **Kademeli otonomi**: küçük değişiklikler otomatik, büyük değişiklikler (örn. günlük bütçenin %50'sinden fazla artış, kampanya tamamen kapatma) insan onayına düşer — bunu dilerseniz arayüzden "tam otomatik" moda alabilirsiniz
- **Her kararın gerekçeli log'u** (Claude neden bu kararı verdi, hangi verilere baktı)
- **Kill switch**: tek tıkla tüm otomasyonu durdurma

Bunlar açık/kapalı switch'ler olarak arayüze konulacak; isterseniz hepsini kapatıp gerçekten tam otonom çalıştırabilirsiniz, ama başlangıçta açık tutmanızı öneririm.

---

## 1. Claude Sistem Promptu

Bu prompt, günlük otomasyon döngüsünde Claude API'ye (Sonnet model, düşük maliyetli ve hızlı olduğu için önerilir) her çalıştırmada `system` parametresi olarak gönderilecek.

```
Sen Sonuç Yayınları'nın Meta (Instagram/Facebook) reklam hesabını yöneten otonom bir 
reklam optimizasyon ajanısın. Görevin, insan müdahalesi olmadan reklam performansını 
analiz etmek ve markanın büyüme hedeflerine hizmet eden kararlar almaktır.

## MARKA BAĞLAMI
Sonuç Yayınları, YKS/TYT-AYT üniversite sınavlarına hazırlanan lise öğrencilerine 
yönelik kitap ve eğitim materyali satan bir yayınevidir. Hedef kitle: 15-18 yaş 
öğrenciler ve onların ebeveynleri (18-45 yaş, satın alma kararını çoğunlukla ebeveyn 
verir). İçerik tonu: motive edici, güven veren, "başarabilirsin" mesajı; sınav 
teknikleri, öğrenci başarı hikayeleri, kitap setleri öne çıkan formatlar.

## HEDEF: BİLİNİRLİK (AWARENESS)
Bu hesaptaki tüm kampanyaların birincil amacı satış/dönüşüm değil, MARKA BİLİNİRLİĞİ 
ve erişimdir. Buna göre optimize ettiğin metrikler önem sırasına göre:
1. Hedef kitleye ulaşan benzersiz kişi sayısı (Reach) ve bunun maliyeti (CPM/CPR)
2. Etkileşim oranı (beğeni+yorum+paylaşım+kaydetme / erişim) — düşük etkileşim, 
   yanlış kitle veya zayıf yaratıcı içerik sinyalidir
3. Video izlenme oranı (ThruPlay / %75 izlenme) — video reklamlarda
4. Sıklık (Frequency) — 3.5'i geçen reklam kitlesi doygunlaşmış sayılır, yorulmuştur
5. Tıklama oranı (CTR) — ikincil sinyal, birincil karar kriteri değil

Satış/dönüşüm kampanyaları bu sistemin kapsamı DIŞINDADIR; eğer hesapta böyle bir 
kampanya görürsen dokunma, sadece rapor et.

## GÜNLÜK GÖREV AKIŞI
Her çalıştırmada sana şu veriler JSON formatında verilecek:
- Son 24 saat, son 3 gün ve son 7 günlük performans verisi (her reklam seti/reklam 
  bazında: harcama, erişim, sıklık, CPM, etkileşim oranı, CTR, durum)
- Her reklamın mevcut günlük bütçesi ve toplam kampanya bütçesi
- Hesabın kalan aylık bütçesi
- Devam eden onay bekleyen kararların listesi (varsa)

Bu veriyle şu sırayla analiz yap:

### ADIM 1 — Sağlık taraması
Her aktif reklamı şu kriterlere göre sınıflandır:
- 🟢 SAĞLIKLI: Etkileşim oranı hesap ortalamasının üzerinde VEYA CPM hesap ortalamasının 
  altında, sıklık < 3.5, minimum 1000 gösterim almış (istatistiksel anlamlılık için)
- 🟡 İZLENMELİ: Sınırda performans, henüz yeterli veri yok (<1000 gösterim, <3 gün 
  yayında) — HENÜZ AKSİYON ALMA, veri toplanmaya devam etsin
- 🔴 ZAYIF: Etkileşim oranı hesap ortalamasının belirgin altında (>%40 fark) VE en az 
  3 gün / 1000+ gösterim yayında VEYA sıklık 3.5'i geçmiş VEYA CPM hesap ortalamasının 
  2 katından fazla

### ADIM 2 — Karar
- 🟢 SAĞLIKLI reklamlar için: bütçe artışı değerlendir. Tek seferde mevcut bütçenin 
  en fazla %20'si kadar artır. Art arda 3 gün sağlıklıysa tekrar %20 artırabilirsin. 
  Asla tek adımda %20'yi aşma (ani artış öğrenme fazını bozar, algoritma yeniden 
  dengeye oturmaya çalışır).
- 🟡 İZLENMELİ reklamlar için: dokunma, sadece not düş ("veri yetersiz, X gün sonra 
  tekrar değerlendir").
- 🔴 ZAYIF reklamlar için, sırayla dene:
  a) Eğer sıklık yüksek ama etkileşim makulse → hedef kitleyi genişletmeyi öner 
     (otomatik yapma, insan kararına bırak — kitle değişikliği yaratıcı stratejiyi 
     etkiler)
  b) Eğer etkileşim düşük ve 5+ gündür böyleyse → bütçeyi %50 azalt, 2 gün daha izle
  c) Eğer 7+ gündür zayıf ve bütçe azaltma işe yaramadıysa → reklamı DURDUR (pause), 
     nedenini logla
  d) Kampanyanın TAMAMINI durdurma kararını asla otomatik verme — bunu her zaman 
     insan onayına gönder

### ADIM 3 — Bütçe dağılımı
Toplam günlük bütçe sabit kalacaksa (kullanıcı arayüzden "sabit toplam bütçe" modunu 
seçtiyse), zayıf reklamlardan kestiğin bütçeyi sağlıklı reklamlara yeniden dağıt. 
Tek bir reklama kampanya toplam bütçesinin %60'ından fazlasını asla verme (risk 
dağılımı için).

### ADIM 4 — Raporlama
Her karar için şu formatta yapılandırılmış çıktı üret (JSON):
{
  "tarih": "...",
  "kararlar": [
    {
      "reklam_id": "...",
      "reklam_adi": "...",
      "durum_sinifi": "SAĞLIKLI | İZLENMELİ | ZAYIF",
      "aksiyon": "BUTCE_ARTIR | BUTCE_AZALT | DURAKLAT | DOKUNMA | ONAYA_GONDER",
      "eski_deger": ...,
      "yeni_deger": ...,
      "gerekce": "İnsan tarafından okunabilir, veriye dayalı, 1-2 cümlelik açıklama",
      "guven_skoru": "yüksek | orta | düşük",
      "otomatik_uygulanabilir": true/false
    }
  ],
  "genel_ozet": "Hesabın günlük durumu, dikkat çekici trendler, öneriler",
  "insan_onayi_gereken": [ ...ONAYA_GONDER işaretli kararların listesi... ]
}

## SERT SINIRLAR (bunları asla ihlal etme)
- Tek bir bütçe değişikliği kampanya/reklam setinin bütçesinin ±%20'sini aşamaz
- Günlük toplam hesap harcaması, kullanıcının arayüzden belirlediği tavanı aşamaz 
  (bu zaten kod seviyesinde de kontrol edilecek, ama sen de öneri verirken bu tavanı 
  bilerek öner)
- Yeni kampanya OLUŞTURMA yetkisi yok — sadece MEVCUT kampanya/reklam seti/reklamları 
  yönetiyorsun
- Hedef kitle (targeting) değişikliği, reklam metni/görseli değişikliği için sadece 
  ÖNERİ üret, otomatik uygulama — bunlar yaratıcı/stratejik kararlardır
- İstatistiksel olarak anlamsız veriyle (< 1000 gösterim veya < 3 gün) asla kalıcı 
  aksiyon (durdurma, büyük bütçe kesintisi) alma
- Emin değilsen, aksiyonu ONAYA_GONDER olarak işaretle — yanlış otomatik karar, 
  hiç karar vermemekten daha kötüdür

## MARKA SESİ KONTROLÜ (reklam metni/görsel önerirken)
Eğitim sektöründe güven çok önemlidir. Öneri üretirken şunlardan kaçın:
- Abartılı/gerçekçi olmayan başarı vaatleri ("Kesin %100 kazanırsın" gibi)
- Öğrenciler üzerinde kaygı/korku odaklı dil ("Bu kitabı almazsan başarısız olursun")
Bunun yerine motive edici, kanıta dayalı (öğrenci yorumları, deneme sonuçları) dil öner.

Şimdi sana verilen performans verisini analiz et ve yukarıdaki formatta karar üret.
```

---

## 2. Python Mimarisi

### 2.1 Genel akış

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Meta Ads API    │────▶│  Veri Toplayıcı   │────▶│   PostgreSQL/    │
│  (Marketing API) │     │  (data_collector) │     │   SQLite DB      │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                             │
┌─────────────────┐     ┌──────────────────┐               ▼
│  Streamlit       │◀───▶│  FastAPI Backend  │◀───┌─────────────────┐
│  Arayüz (UI)      │     │  (API + kurallar) │     │  Claude Agent    │
└─────────────────┘     └──────────────────┘     │  (karar motoru)  │
                                                    └─────────────────┘
                                                             │
                              APScheduler (her gün 09:00) ──┘
                                       │
                                       ▼
                           ┌──────────────────────┐
                           │ Meta Ads API'ye geri  │
                           │ yaz (bütçe/durum      │
                           │ değişikliği)          │
                           └──────────────────────┘
```

### 2.2 Proje klasör yapısı

```
sonuc-reklam-otomasyon/
├── config/
│   ├── settings.yaml          # bütçe tavanları, eşikler, mod (tam-otomatik/onaylı)
│   └── .env                   # META_ACCESS_TOKEN, CLAUDE_API_KEY, DB_URL
├── core/
│   ├── meta_client.py         # Meta Marketing API sarmalayıcı (facebook_business SDK)
│   ├── data_collector.py      # Insights çekme, DB'ye yazma
│   ├── claude_agent.py        # Claude API çağrısı, sistem promptu, JSON parse
│   ├── decision_executor.py   # Claude kararlarını Meta API'ye uygulama + sert limit kontrolü
│   ├── rules_engine.py        # Kod seviyeli hard-limit kontrolleri (Claude'dan bağımsız)
│   └── models.py              # SQLAlchemy modelleri (Campaign, AdSet, Ad, DecisionLog)
├── scheduler/
│   └── daily_job.py           # APScheduler ile her gün tetiklenen ana döngü
├── ui/
│   ├── app.py                 # Streamlit ana sayfa
│   ├── pages/
│   │   ├── 1_Dashboard.py     # Genel performans özeti, grafikler
│   │   ├── 2_Kampanyalar.py   # Aktif kampanya/reklam listesi, manuel müdahale
│   │   ├── 3_Kurallar.py      # Bütçe tavanı, eşik, otomasyon modu ayarları
│   │   ├── 4_Onay_Kuyrugu.py  # Claude'un ONAYA_GONDER dediği kararlar, onayla/reddet
│   │   └── 5_Karar_Gecmisi.py # Tüm geçmiş kararlar + gerekçeleri (audit log)
│   └── components/
├── database/
│   └── sonuc_ads.db           # SQLite (veya Postgres bağlantısı)
├── requirements.txt
└── main.py                    # Uygulamayı başlatan giriş noktası
```

### 2.3 Ana bileşenler (kod iskeletleri)

**`config/settings.yaml`** — Arayüzden değiştirilebilir, kod bunu okuyup uygular:
```yaml
otomasyon_modu: "onayli"        # "onayli" | "tam_otomatik"
gunluk_hesap_butce_tavani: 1500  # TRY, sert limit
max_tek_islem_butce_degisim_yuzde: 20
min_gosterim_esigi: 1000
min_gun_esigi: 3
kill_switch: false               # true olursa hiçbir aksiyon uygulanmaz
calisma_saati: "09:00"
hedef_kampanyalar:                # sadece bu kampanya ID'leri yönetilir
  - "act_XXXXXXXXX/campaign_id_1"
```

**`core/meta_client.py`** — Meta Marketing API bağlantısı:
```python
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.ad import Ad
from facebook_business.adobjects.adset import AdSet

class MetaAdsClient:
    def __init__(self, access_token, app_id, app_secret, ad_account_id):
        FacebookAdsApi.init(app_id, app_secret, access_token)
        self.account = AdAccount(ad_account_id)

    def get_insights(self, date_preset="last_7d"):
        """Reklam bazında erişim, sıklık, CPM, etkileşim, harcama çeker."""
        fields = ['ad_id', 'ad_name', 'reach', 'frequency', 'cpm',
                  'spend', 'engagement_rate', 'video_thruplay_watched_actions']
        return self.account.get_insights(
            fields=fields,
            params={'level': 'ad', 'date_preset': date_preset}
        )

    def update_ad_budget(self, adset_id, new_daily_budget):
        adset = AdSet(adset_id)
        adset.api_update(params={'daily_budget': int(new_daily_budget * 100)})

    def pause_ad(self, ad_id):
        Ad(ad_id).api_update(params={'status': 'PAUSED'})
```

**`core/claude_agent.py`** — Claude'a veri gönderip yapılandırılmış karar alma:
```python
import anthropic, json

SYSTEM_PROMPT = open("config/system_prompt.txt", encoding="utf-8").read()

client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

def get_daily_decisions(performance_data: dict) -> dict:
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Bugünkü performans verisi:\n{json.dumps(performance_data, ensure_ascii=False)}"
        }]
    )
    text = response.content[0].text
    # JSON fence temizliği
    clean = text.replace("```json", "").replace("```", "").strip()
    return json.loads(clean)
```

**`core/rules_engine.py`** — Claude'dan BAĞIMSIZ, kod seviyeli sert kontrol (güvenlik ağı):
```python
def validate_decision(decision, settings):
    """Claude'un önerdiği her kararı, kod seviyeli sert limitlerle çapraz kontrol eder.
    Limit ihlali varsa kararı otomatik olarak ONAYA_GONDER'e çevirir."""
    if settings["kill_switch"]:
        decision["aksiyon"] = "DOKUNMA"
        decision["gerekce"] += " [KILL SWITCH AKTİF]"
        return decision

    if decision["aksiyon"] in ("BUTCE_ARTIR", "BUTCE_AZALT"):
        degisim_yuzde = abs(decision["yeni_deger"] - decision["eski_deger"]) / decision["eski_deger"] * 100
        if degisim_yuzde > settings["max_tek_islem_butce_degisim_yuzde"]:
            decision["aksiyon"] = "ONAYA_GONDER"
            decision["gerekce"] += " [Limit aşımı nedeniyle onaya düştü]"

    if settings["otomasyon_modu"] == "onayli" and decision["aksiyon"] != "DOKUNMA":
        decision["otomatik_uygulanabilir"] = False

    return decision
```

**`scheduler/daily_job.py`** — Günlük döngü:
```python
from apscheduler.schedulers.blocking import BlockingScheduler

def run_daily_cycle():
    settings = load_settings()
    if settings["kill_switch"]:
        log("Kill switch aktif, döngü atlandı.")
        return

    raw_data = data_collector.collect_last_n_days(7)
    claude_output = claude_agent.get_daily_decisions(raw_data)

    for decision in claude_output["kararlar"]:
        validated = rules_engine.validate_decision(decision, settings)
        db.save_decision_log(validated)
        if validated["otomatik_uygulanabilir"] and validated["aksiyon"] != "DOKUNMA":
            decision_executor.apply(validated)
        else:
            db.add_to_approval_queue(validated)

    notify_summary(claude_output["genel_ozet"])

scheduler = BlockingScheduler()
scheduler.add_job(run_daily_cycle, 'cron', hour=9, minute=0)
```

### 2.4 Streamlit arayüzü — sayfa içerikleri

- **Dashboard**: Günlük/haftalık erişim, CPM, etkileşim grafikleri (plotly), aktif reklam sayısı, kalan bütçe göstergesi.
- **Kampanyalar**: Tablo halinde tüm aktif reklamlar, sağlık durumu renk kodlu (🟢🟡🔴), manuel "şimdi durdur / bütçe değiştir" butonları.
- **Kurallar**: `settings.yaml`'ı UI'dan düzenleme — bütçe tavanı, otomasyon modu (kayar switch: "Onaylı" ↔ "Tam Otomatik"), kill switch butonu.
- **Onay Kuyruğu**: Claude'un ONAYA_GONDER dediği her karar burada listelenir, gerekçesiyle birlikte; "Onayla" / "Reddet" butonları.
- **Karar Geçmişi**: Tüm geçmiş kararların audit log'u — hangi tarihte, hangi reklama, neden, kim onayladı (Claude/insan).

### 2.5 Gerekli kütüphaneler

```
facebook-business      # Meta Marketing API resmi SDK
anthropic               # Claude API
streamlit               # Arayüz
apscheduler             # Zamanlayıcı
sqlalchemy              # ORM
pandas, plotly          # Veri işleme ve görselleştirme
python-dotenv           # .env yönetimi
pyyaml                  # settings.yaml
```

---

## 3. Kurulum için gerekenler (sizin tarafınızda)

1. **Meta İş Yöneticisi** hesabında bir **Sistem Kullanıcısı** oluşturup uzun ömürlü (long-lived) bir `access_token` alın, `ads_management` ve `ads_read` izinleriyle.
2. Reklam hesabınızın ID'sini (`act_XXXXXXXXX`) alın.
3. Anthropic Console'dan bir **Claude API anahtarı** oluşturun.
4. Yukarıdaki klasör yapısını kurup `.env` dosyasına bu bilgileri girin.

---

Bu doküman hem sistem promptunu hem de onu çalıştıracak Python mimarisini içeriyor — `config/settings.yaml` ve arayüz üzerinden bütçe tavanı, otomasyon modu ve eşikleri değiştirerek sistemi istediğiniz otonomi seviyesine getirebilirsiniz. İsterseniz bir sonraki adımda bu iskeletin çalışan bir ilk versiyonunu (kod dosyaları olarak) oluşturabilirim.
