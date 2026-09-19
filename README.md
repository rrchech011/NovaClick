# ⚡ NovaClick

**🇹🇷 [Türkçe](#-türkçe) · 🇬🇧 [English](#-english)**

![NovaClick screenshot](NovaClicker.png)

> 🤖 **Bu proje, Anthropic'in yapay zekâ asistanı [Claude](https://claude.ai) ile birlikte geliştirilmiştir.**
> 🤖 **Built together with [Claude](https://claude.ai), Anthropic's AI assistant.**

**⬇️ [Download / İndir](../../releases/latest)** — `novaclick.exe` (Windows 10/11, 64-bit)

---

# 🇹🇷 Türkçe

Modern arayüzlü, gelişmiş ve açık kaynaklı otomatik tıklayıcı (autoclicker). Windows için geliştirildi. Arayüz **Türkçe ve İngilizce** (Ayarlar → Dil).

## Özellikler

- **Hassas aralık:** saat / dakika / saniye / milisaniye, hızlı CPS ön ayarları, rastgele sapma (jitter)
- **Basılı tutma süresi:** oyunların kaçırdığı tıklamaları azaltır
- **4 tıklama yöntemi:** İmleç · Sabit nokta · **Pencere (oyun modu)** · Arka plan
- **Pencere modu:** seçtiğin pencerenin belirli noktasına gerçek fare girdisiyle tıklar, pencere aktif değilken duraklar (ya da öne getirir)
- **Nokta dizisi ve makro kaydı:** birden fazla noktaya sırayla tıkla, her noktaya kendi bekleme süresini ver, tıklamalarını kaydet (`F7`)
- **Oyun ön ayarları:** tıklama simülatörü, hızlı, insan gibi, turbo
- **Global kısayol:** varsayılan `F6`, değiştirilebilir; Aç/Kapa ve Basılı Tut
- **Güvenlik:** başlangıç gecikmesi, süre sınırı, tekrar sayısı, acil durdurma (fareyi sol üst köşeye götür)
- **Canlı istatistik:** tıklama sayısı, anlık CPS, süre ve CPS grafiği
- **Test tıklaması ve tanılama:** seçtiğin yöntemin hedefte çalışıp çalışmadığını 3 tıklamayla dene; kısayolun alınıp alınmadığını ve yönetici yetkisi uyumsuzluğunu gör
- **Profiller**, 5 vurgu rengi, her zaman üstte, sistem tepsisine küçültme

## Kurulum

### 1) Hazır exe (en kolayı)
[Releases](../../releases/latest) sayfasından `novaclick.exe` dosyasını indir ve çift tıkla. Python kurmana gerek yok. Exe, GitHub Actions ile bu depodaki kaynak koddan otomatik üretilir.

> ⚠️ İlk açılışta Windows bir uyarı gösterebilir. Bu normaldir, [aşağıda](#windows-uyarısı-smartscreen) anlattım.

### 2) Kaynak koddan çalıştırma
[Python 3.10+](https://www.python.org/downloads/) kurulu olmalı (kurulumda **Add python.exe to PATH** işaretli olsun).

```bash
git clone https://github.com/rrchech011/NovaClick.git
cd NovaClick
pip install -r requirements.txt
python novaclick.py
```

### 3) Kendi exe'ni üret
`build.bat` dosyasına çift tıkla.

## Tıklama yöntemleri

| Yöntem | Ne yapar | Ne zaman |
|---|---|---|
| **İmleç** | Fare neredeyse orada tıklar | Basit kullanım |
| **Sabit** | Ekranda sabit bir koordinata tıklar | Tek ekranlı, sabit arayüzler |
| **Pencere** | Seçilen pencerenin içindeki noktaya gerçek fare girdisiyle tıklar; pencere aktif değilse duraklar veya öne getirir | **Oyunlar** |
| **Arka plan** | Pencereye tıklama mesajı yollar, fareyi kullanmaz | Tarayıcı, klasik programlar |

### Oyunlar için notlar
- **Basılı tutma** süresini 10–30 ms yap. Oyunlar tıklamayı tek karede yakalamaya çalışır.
- Oyunlarda **Pencere** yöntemini kullan. **Arka plan** yöntemi çoğu oyunda çalışmaz, çünkü oyunlar bu mesajları yok sayar.
- Oyun yönetici olarak çalışıyorsa NovaClick'i de yönetici olarak başlat (**Ayarlar → Tanılama → Yönetici olarak yeniden başlat**). Aksi halde Windows hem tıklamayı hem kısayolu engeller.
- Pencere modunda gerçek fare kullanıldığı için, oyun aktifken fareni başka iş için kullanamazsın. **Öne getir** seçeneği bunu hafifletir ama deneyseldir ve her tıklamada kısa bir titreme yapar.
- Bazı oyunlar otomatik tıklamayı yasaklar. Kuralları kontrol et.

## Kullanım

1. **Tıklama** sayfasında aralığı ve tıklama ayarlarını seç.
2. **Hedef** sayfasında yöntemi seç. Pencere/Arka plan için **Pencere seç**'e bas ve hedef pencerede tıklanmasını istediğin noktaya bir kez tıkla.
3. `F6` ile başlat, tekrar `F6` ile durdur.
4. Sabit/İmleç yönteminde acil durdurma için fareyi ekranın sol üst köşesine götür.

## Windows uyarısı (SmartScreen)

Exe'yi ilk çalıştırdığında **"Windows kişisel bilgisayarınızı korudu"** ekranı çıkabilir. Bunun nedeni exe'nin henüz dijital olarak imzalı olmaması ve Windows'un yeni dosyalara temkinli davranmasıdır; dosyanın zararlı olduğu anlamına gelmez.

**Çalıştırmak için:** **Ek bilgi** → **Yine de çalıştır**.

**Güvenmek istersen:**
- Kaynak kodun tamamı bu depoda açık; exe **Actions** sekmesinde görülebilen bir işlemle bu koddan üretilir.
- Program yalnızca seçtiğin kısayol tuşlarını (`F6`, `F7`) dinler, yazdıklarını kaydetmez. İnternete bağlanmaz; yazdığı tek dosya ayar dosyasıdır (`~/.novaclick.json`).
- Exe'yi [VirusTotal](https://www.virustotal.com)'a yükleyip kontrol edebilirsin.
- İstersen exe yerine kaynak koddan çalıştır ya da `build.bat` ile kendin üret.

## Sorumlu kullanım

Bu araç kişisel kullanım ve otomasyon içindir. Çevrimiçi oyunlarda ve kuralların otomatik tıklamayı yasakladığı servislerde kullanmak hesabının kapatılmasına yol açabilir. Sorumluluk kullanıcıya aittir.

---

# 🇬🇧 English

A modern, feature-rich, open-source auto clicker for Windows. The interface is available in **English and Turkish** (Settings → Language).

## Features

- **Precise interval:** hours / minutes / seconds / milliseconds, quick CPS presets, random jitter
- **Hold time:** reduces the clicks that games miss
- **4 click methods:** Cursor · Fixed point · **Window (game mode)** · Background
- **Window mode:** clicks a spot inside the chosen window with real mouse input, pauses while the window is inactive (or brings it to the front)
- **Point sequences & macro recorder:** click several points in order, give each point its own wait time, record your clicks (`F7`)
- **Game presets:** click simulator, fast, human-like, turbo
- **Global hotkey:** `F6` by default, changeable; toggle or hold
- **Safety:** start delay, time limit, repeat count, failsafe corner
- **Live stats:** click count, live CPS, elapsed time and a CPS graph
- **Test click & diagnostics:** try the chosen method with 3 clicks, see whether the hotkey is received and whether there is an administrator-rights mismatch
- **Profiles**, 5 accent colors, always on top, minimize to tray

## Installation

### 1) Ready-made exe (easiest)
Download `novaclick.exe` from the [Releases](../../releases/latest) page and double-click it. No Python needed. The exe is built automatically from the source code in this repository with GitHub Actions.

> ⚠️ Windows may show a warning on first launch. That is normal, see [below](#windows-smartscreen-warning).

### 2) Run from source
Requires [Python 3.10+](https://www.python.org/downloads/) (tick **Add python.exe to PATH** during setup).

```bash
git clone https://github.com/rrchech011/NovaClick.git
cd NovaClick
pip install -r requirements.txt
python novaclick.py
```

### 3) Build your own exe
Double-click `build.bat`.

## Click methods

| Method | What it does | Use it for |
|---|---|---|
| **Cursor** | Clicks wherever the mouse is | Simple use |
| **Fixed** | Clicks a fixed screen coordinate | Single-screen, static UIs |
| **Window** | Clicks a spot inside the chosen window with real mouse input; pauses or brings the window to front when it is inactive | **Games** |
| **Background** | Sends click messages to a window without using your mouse | Browsers, classic apps |

### Notes for games
- Set **Hold time** to 10–30 ms. Games try to catch a click within a single frame.
- Use the **Window** method for games. **Background** does not work in most games because they ignore those messages.
- If the game runs as administrator, start NovaClick as administrator too (**Settings → Diagnostics → Restart as administrator**). Otherwise Windows blocks both the clicks and the hotkey.
- Window mode uses the real mouse, so you cannot use your mouse for other things while the game is active. **Bring to front** eases this but is experimental and flickers briefly on every click.
- Some games forbid automated clicking. Check their rules.

## Usage

1. Choose the interval and click options on the **Clicking** page.
2. Choose the method on the **Target** page. For Window/Background, press **Pick window** and click the spot you want clicked once in the target window.
3. Press `F6` to start and `F6` again to stop.
4. With Fixed/Cursor, move the mouse to the top-left corner of the screen for an emergency stop.

## Windows SmartScreen warning

On first launch Windows may show **"Windows protected your PC"**. This is because the exe is not code-signed yet and Windows is cautious with new files. It does not mean the file is harmful.

**To run it:** **More info** → **Run anyway**.

**If you want to verify:**
- The full source is in this repo; the exe is built from it by a process you can inspect in the **Actions** tab.
- The program only listens for your chosen hotkeys (`F6`, `F7`) and does not log what you type. It makes no network connections; the only file it writes is the settings file (`~/.novaclick.json`).
- You can upload the exe to [VirusTotal](https://www.virustotal.com).
- Or run from source / build it yourself with `build.bat`.

## Responsible use

This tool is for personal use and automation. Using it in online games or services that forbid automated clicking may get your account banned. Use at your own risk.

---

## License / Lisans

[MIT](LICENSE)
