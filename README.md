# weather_background

Hình nền động cho Linux: chọn ảnh theo **góc mặt trời thật** tại toạ độ của bạn,
rồi phủ hiệu ứng theo **thời tiết thực tế** lấy từ Open-Meteo.

Chỉ cần **4 ảnh gốc** (`night`, `dawn`, `day`, `dusk`) thay vì 20+ ảnh, vì lớp
thời tiết được xử lý bằng Pillow lúc chạy.

## Cài đặt

```bash
cd ~/Projects/weather_background
chmod +x install.sh
./install.sh
```

Script sẽ tạo venv, cài `astral` + `Pillow`, sinh 4 ảnh nền mặc định nếu thư mục
`wallpapers/` còn trống, rồi bật systemd user timer chạy mỗi 15 phút.

## Đóng gói .deb để cài lên máy khác

```bash
./packaging/build-deb.sh          # ra build/weather-background_1.0.0_all.deb
./packaging/build-deb.sh 1.1.0    # đổi version
```

Cần chạy `./install.sh` trước một lần, vì script build lấy `astral` từ `.venv`
để nhúng vào gói, và dùng Pillow để nén ảnh nền sang JPEG q92 4:4:4. PNG của
ảnh có dither nặng tới ~3 MB/ảnh, JPEG q92 nhỏ gần 5 lần mà mắt không phân
biệt được.

Cài trên máy đích:

```bash
sudo apt install ./weather-background_1.0.0_all.deb
systemctl --user daemon-reload
systemctl --user enable --now weather-wallpaper.timer
```

Gói **không tự bật timer** — mỗi user tự bật, vì đây là user service.

### Bố cục sau khi cài

| Đường dẫn | Nội dung |
|---|---|
| `/usr/bin/weather-wallpaper` | Lệnh chính |
| `/usr/lib/weather-background/` | `wallpaper.py` + `_vendor/astral` |
| `/usr/lib/systemd/user/` | service + timer |
| `/etc/xdg/weather-background/config.toml` | Config hệ thống (conffile) |
| `/usr/share/weather-background/wallpapers/` | 4 ảnh nền mặc định |

Thứ tự ưu tiên khi chạy — config: `~/.config/weather-background/config.toml`
→ `/etc/xdg/...` → thư mục source. Ảnh nền:
`~/.local/share/weather-background/wallpapers` → thư mục source →
`/usr/share/weather-background/wallpapers`.

Nên mỗi user chỉ cần bỏ ảnh riêng vào `~/.local/share/weather-background/wallpapers/`
là ghi đè được bộ mặc định, không đụng tới `/usr`.

### Vì sao nhúng astral

`python3-astral` trong repo Ubuntu 22.04 là bản **1.6.1**, API khác hẳn (không có
`Observer`). Gói nhúng sẵn astral 3.2 — thuần Python, Apache-2.0 — vào `_vendor/`.
Khi chạy từ thư mục source thì không có `_vendor`, script tự dùng bản trong venv.

Phụ thuộc còn lại đều có sẵn trong repo: `python3-pil`, và `python3-tomli` cho
Python 3.10 (từ 3.11 trở lên dùng `tomllib` của stdlib).

## Cấu hình

Sửa `config.toml`:

| Khoá | Ý nghĩa |
|---|---|
| `latitude` / `longitude` | Toạ độ tính mặt trời và thời tiết. Mặc định Hà Nội. |
| `wallpapers` | Thư mục chứa ảnh gốc. |
| `setter` | `auto`, `gnome`, `kde`, `swaybg`, `feh`, `none`. |
| `resolution` | Ví dụ `"2560x1440"`. Bỏ trống để giữ nguyên kích thước ảnh gốc. |
| `weather.enabled` | `false` = chỉ đổi theo mặt trời, không gọi mạng. |

## Thay ảnh gốc

Đặt 4 file vào `wallpapers/` với đúng tên: `night`, `dawn`, `day`, `dusk`
(đuôi `.jpg`, `.png` hoặc `.webp`).

Nếu bạn có file `.heic` dynamic wallpaper của macOS, tách ra bằng:

```bash
sudo apt install libheif-examples
heif-convert BigSur.heic frame.png     # ra 16 frame
```

Rồi chọn 4 frame tiêu biểu và đổi tên tương ứng.

## Chạy tay / gỡ lỗi

```bash
.venv/bin/python wallpaper.py                       # chạy bình thường
.venv/bin/python wallpaper.py --dry-run             # tạo ảnh, không đổi nền
.venv/bin/python wallpaper.py --weather storm       # ép trạng thái thời tiết
.venv/bin/python wallpaper.py --phase dusk          # ép khung giờ
.venv/bin/python wallpaper.py --offline             # không gọi API
.venv/bin/python wallpaper.py --generate-bases      # sinh lại 4 ảnh nền
```

## Cửa sổ cài đặt

```bash
weather-background-settings
```

Cũng xuất hiện trong danh sách ứng dụng với tên **Weather Background**.

**Tab Ảnh nền** — chọn chủ đề (`Núi và hồ` mặc định, `Biển`, `Rừng`, `Sa mạc`),
bấm *Tìm ảnh*, rồi chọn ảnh cho từng khung giờ. Ảnh lấy từ **Wikimedia Commons**
qua API, tải về `~/.local/share/weather-background/wallpapers/` ở đúng độ phân
giải trong config — không kéo bản gốc hàng chục MB về rồi mới thu nhỏ.

Ghi công (tiêu đề, tác giả, giấy phép, link nguồn) lưu vào `credits.txt` cạnh ảnh.

**Tab Cấu hình** — toạ độ, độ phân giải, cách đặt hình nền, bật/tắt thời tiết.
Ghi vào `~/.config/weather-background/config.toml`, đè lên config hệ thống.

### Lọc kết quả

Commons trả về khá nhiều bản khắc cổ, bản đồ và ảnh vệ tinh vì trùng từ khoá địa
danh. Từ khoá âm (`-map -satellite`) **không dùng được** — Commons khớp chúng cả
trong category và template nên loại nhầm gần hết kết quả. Thay vào đó `catalog.py`
lọc phía client: bỏ ảnh hẹp hơn 1920px, tỉ lệ ngoài khoảng 1.45–2.40, và ảnh có
độ bão hoà trung bình gần 0 (bản khắc đen trắng, ảnh vệ tinh hồng ngoại).

## Ảnh nền mặc định

Gói kèm **32 ảnh [SolarShift](https://github.com/TemujinCalidius/SolarShift)**
(4 mùa × 8 khung giờ) — cùng một ngôi làng trung cổ vẽ theo phong cách low-poly,
do AI sinh, giấy phép MIT © 2026 Samuel Lison. Ảnh gốc 5504×3072 PNG (~18 MB mỗi
ảnh, 570 MB cả bộ) được thu về 2560×1440 JPEG q88 khi đóng gói, còn ~21 MB.

Tải ảnh gốc bằng `./packaging/fetch-solarshift.sh`, script build tự chuyển đổi. Không
có thư mục đó thì gói vẫn build được, chỉ thiếu phần ảnh theo mùa.

## Ảnh nền dựng bằng code

`--generate-bases` dựng cảnh núi bằng Pillow, không phải gradient phẳng:

- bầu trời nội suy trong **không gian tuyến tính** (trộn thẳng trong sRGB sẽ ra màu xám đục);
- quầng sáng mặt trời/trăng vẽ bằng mask tròn, cộng đĩa vẽ ở full resolution rồi làm mềm viền;
- ba rặng núi sinh bằng **dịch chuyển trung điểm 1 chiều**, rặng xa pha dần về màu chân trời (phối cảnh khí quyển);
- sao thưa dần khi xuống gần chân trời, tắt hẳn ở `day`;
- nhiễu Gauss nhẹ để phá banding của gradient 8-bit trên màn hình lớn.

Sửa dict `SCENES` trong `wallpaper.py` để đổi bảng màu từng khung giờ, `RIDGES`
để đổi số lượng / độ cao / độ pha sương của các rặng núi, `HORIZON` để dời đường
chân trời. Mất khoảng 1,2 giây mỗi ảnh ở 2560×1440.

Muốn dùng ảnh chụp thật thì cứ ghi đè 4 file trong thư mục ảnh nền như mô tả ở trên.

## Khung giờ và mùa

8 khung giờ, chọn theo góc mặt trời thật và chiều lên/xuống:

| Khung | Chiều | Điều kiện |
|---|---|---|
| `night` | — | dưới −6° (lên) / dưới −9° (xuống) |
| `dawn` | lên | −6° … 8° |
| `morning` | lên | 8° … *top* |
| `midday` | — | trên *top* |
| `afternoon` | xuống | 12° … *top* |
| `golden_hour` | xuống | 3° … 12° |
| `dusk` | xuống | −3° … 3° |
| `twilight` | xuống | −9° … −3° |

`top` **không cố định**. Ở vĩ độ cao mùa đông mặt trời không bao giờ lên tới
28°, nên ngưỡng tuyệt đối sẽ khiến `midday` không bao giờ xảy ra. Thay vào đó
`top = min(28°, 80% × độ cao lúc chính ngọ)` của chính ngày hôm đó. Vùng nhiệt
đới chạm trần 28° nên hành vi không đổi; London tháng 12 thì `top` tụt xuống
theo và `midday` vẫn có.

Các ngưỡng được ép không giảm dần, nên ngày quá ngắn ở vùng cực chỉ làm dải
tương ứng rỗng đi — đúng nghĩa: hôm đó không có khung giờ đó. Đo thử ở Tromsø
(70°N): tháng 6 không có `night`/`dusk`/`twilight` (mặt trời không lặn), tháng
12 không có `midday` (mặt trời không mọc).

Khung ngắn nhất (`dusk`, `twilight` ở vùng nhiệt đới) kéo dài 27–28 phút, dài
hơn chu kỳ timer 15 phút nên không bị bỏ sót.

Sửa `RISING_BANDS` / `FALLING_BANDS` và `MIDDAY_CAP` trong `wallpaper.py` để đổi.

### Mùa

Đặt `season` trong `[display]`: `auto` (suy từ tháng và bán cầu theo `latitude`),
`off`, hoặc tên mùa cụ thể. Ảnh tìm ở `wallpapers/<mùa>/<khung>.jpg` trước, không
có thì lui về `wallpapers/<khung>.jpg`.

### Tương thích ngược

Bộ 4 ảnh cũ (`night`/`dawn`/`day`/`dusk`) vẫn chạy. `PHASE_ALIASES` ánh xạ
`morning`/`midday`/`afternoon` → `day`, `golden_hour` → `dusk`, `twilight` →
`night`. Không cần đổi gì.

## Chỉnh hiệu ứng thời tiết

Dict `EFFECTS` trong `wallpaper.py`, mỗi dòng là
`(saturation, brightness, contrast, (tint_rgb, alpha), blur_radius)`.
Sửa số rồi xem ngay bằng `--dry-run --weather <nhóm>`; ảnh nằm ở
`~/.cache/weather-wallpaper/`.

## Ghi chú

- Nhóm thời tiết map từ mã WMO của Open-Meteo (xem `WMO_GROUPS`).
- Mất mạng thì dùng lại trạng thái lần trước, không làm hỏng hình nền.
- Ảnh output ghi luân phiên vào 2 file `wallpaper_a.jpg` / `wallpaper_b.jpg`
  vì GNOME không reload nếu đường dẫn không đổi.
- KDE Plasma có sẵn plugin *Dynamic Wallpaper* đọc thẳng `.heic` của macOS —
  nếu bạn dùng Plasma và không cần chiều thời tiết thì cài plugin đó nhanh hơn.

## Gỡ

```bash
systemctl --user disable --now weather-wallpaper.timer
rm ~/.config/systemd/user/weather-wallpaper.{service,timer}
systemctl --user daemon-reload
rm -rf ~/.cache/weather-wallpaper
```
