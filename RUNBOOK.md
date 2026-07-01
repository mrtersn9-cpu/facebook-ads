# RUNBOOK

Bu doküman, projeyi yazmamış bir operatörün acil/operasyonel durumlarda ne
yapması gerektiğini anlatır. Kurulum ve genel mimari için [README.md](README.md)'ye bakın.

## "Bot yanlış bir aksiyon aldı, ne yapmalıyım?"

1. **Hemen durdur.** `.env`'de `KILL_SWITCH=true` yapın (veya process'i
   çalıştıran ortamda bu değişkeni ayarlayıp process'i yeniden başlatın/
   sinyalle bilgilendirin). Bir sonraki `run_once()` çağrısı hiçbir dış
   çağrı yapmadan hemen çıkacaktır. Süregelen bir çalıştırma varsa
   `Ctrl+C` (veya `SIGTERM`) gönderin — mevcut aksiyon bitirilir ama yenisi
   başlatılmaz (bkz. `action_executor.install_signal_handlers`).
2. **DRY_RUN'a dönün.** `.env`'de `DRY_RUN=true` yapın. Bu, bir sonraki
   canlı denemeden önce botun kararlarını tekrar güvenle gözlemlemenizi sağlar.
3. **Gerçek hasarı Ads Manager'dan manuel düzeltin.** Bot hiçbir eylemi geri
   almaya çalışmaz (silme/geri alma da riskli bir yazma işlemidir) — bütçeyi
   eski haline getirmek veya bir ad set'i yeniden aktifleştirmek insan kararı
   olmalı.
4. **Kök nedeni `logs/actions.jsonl`'den bulun.** Her kayıtta `adset_id`,
   `action`, `status` (`applied`/`dry_run`/`rejected`/`error`/
   `guardrail_violation`/`shutdown`) ve okunabilir bir `reason` vardır.
   İlgili zaman aralığındaki kayıtları inceleyin:
   ```bash
   grep '"status": "applied"' logs/actions.jsonl | tail -20
   ```
5. **Guardrail sabitlerini gözden geçirin.** Sorun bir guardrail sınırının
   çok gevşek olmasından kaynaklanıyorsa (`MAX_BUDGET_CHANGE_PERCENT`,
   `MAX_DAILY_BUDGET_TOTAL`, vb.), bunları sıkılaştırın — asla "daha hızlı
   optimize etsin" diye gevşetmeyin.

## "Token süresi doldu, nasıl yenilerim?"

- Meta API `code=190` (auth hatası) döndürdüğünde bot **retry yapmaz**,
  hatayı doğrudan loglar/patlatır — bu kasıtlıdır, token yenileme insan işidir.
- `logs/actions.jsonl` veya konsol çıktısında `MetaAuthError` / "Graph API
  auth hatası" arayın.
- Ayrıca `meta_client.check_token_expiry()` her `run_once()` çağrısında
  token'ın süresine bakar; `TOKEN_EXPIRY_WARN_DAYS` (varsayılan 7) gün
  kala loglara "Meta access token N gün içinde sona erecek!" uyarısı düşer
  — bu uyarıyı beklemeden aksiyon almak için loglara periyodik bakın.
- Yeni bir System User token'ı üretip `.env`'deki `META_ACCESS_TOKEN`'ı
  güncelleyin, process'i yeniden başlatın.
- Kalıcı (system user) token'lar `expires_at=0` döner; bu durumda uyarı
  hiç gelmez — token'ı yalnızca izinler değiştiğinde veya elle iptal
  ettiğinizde yenilemeniz gerekir.

## "Guardrail sürekli reddediyor, nasıl teşhis ederim?"

1. `logs/actions.jsonl`'de `"status": "rejected"` kayıtlarının
   `reason`/`rejection_reason` alanına bakın — sebep her zaman insan
   tarafından okunabilir şekilde yazılıdır (ör. "Bilinmeyen/uydurulmuş
   adset_id", "Minimum harcama eşiğinin altında").
2. **Bilinmeyen adset_id** çok sık görülüyorsa: karar motorunun aldığı
   snapshot ile guardrail'in bildiği ad set kümesi arasında bir tutarsızlık
   olabilir (ör. `SCOPE_CAMPAIGN_NAME_FILTER` ayarlıyken Claude eski/başka
   bir ad set öneriyor). `decision_engine.py`'nin gönderdiği snapshot'ı
   `LOG_LEVEL=DEBUG` ile inceleyin.
3. **Minimum harcama eşiği** çok sık tetikleniyorsa `MIN_SPEND_BEFORE_ACTION`
   değerinin hesabınızın tipik günlük harcamasına göre çok yüksek olup
   olmadığını kontrol edin.
4. **Toplam bütçe aşımı (`GuardrailViolation`)** sürekli oluyorsa,
   `MAX_DAILY_BUDGET_TOTAL`'ın gerçek/istenen toplam bütçenizi yansıtıp
   yansıtmadığını kontrol edin — bu bilinçli bir tavan olmalı, rastgele
   büyütülmemeli.
5. Guardrail ihlalleri her zaman (webhook ayarlıysa) Slack'e düşer; bu
   bildirimleri kaçırmayın.

## "Scheduler/servis çöktü mü, nasıl anlarım?"

- Her `run_once()` çağrısı en başta `heartbeat: run_once başlıyor` INFO
  logu yazar (KILL_SWITCH açıkken bile). Bu satırın `RUN_INTERVAL_HOURS`
  aralığından çok daha uzun süre görünmemesi, process'in çökmüş
  olabileceğinin bir işaretidir.
- Sürekli mod (`python main.py`, `--once` olmadan) çalışırken tek bir
  run'daki beklenmeyen hata scheduler'ı öldürmez — `_safe_run_once()`
  hatayı loglayıp bir sonraki çalıştırmayı bekler. Process tamamen
  duruyorsa bu, scheduler'ın kendisinin (ör. OOM, host restart) çöktüğü
  anlamına gelir; işletim sistemi seviyesinde bir restart mekanizması
  (systemd, container restart policy) buna karşı koruma sağlar.

## Haftalık/aylık özet raporu

```bash
python reports/weekly_summary.py       # son 7 gün
python reports/weekly_summary.py 30    # son 30 gün
```

Toplam uygulanan/reddedilen/hata alan aksiyon sayısını ve en çok
değiştirilen ad set'leri özetler.
