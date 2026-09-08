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

Script sẽ tạo venv, cài `astral` + `Pillow`, sinh 4 ảnh gradient tạm nếu thư mục
`wallpapers/` còn trống, rồi bật systemd user timer chạy mỗi 15 phút.

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
.venv/bin/python wallpaper.py --generate-bases      # sinh lại 4 gradient
```

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
