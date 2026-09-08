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

## Ngưỡng phân chia khung giờ

| Khung | Điều kiện góc mặt trời |
|---|---|
| `night` | dưới −6° |
| `dawn` | −6° … +12°, đang lên |
| `day` | trên +12° |
| `dusk` | −6° … +12°, đang xuống |

Đổi ngưỡng trong hàm `solar_phase()`. Ở Hà Nội, `dawn`/`dusk` kéo dài khoảng
50–60 phút mỗi lần.

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
