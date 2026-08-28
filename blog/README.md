# 無名小站風格部落格

一個以早期個人部落格／無名小站氛圍為靈感的簡約 Flask 部落格。

## 功能

- 遊客首頁、文章列表、文章內頁
- 管理員帳號密碼登入
- 新增、編輯、刪除文章
- 文章分類與分類索引
- 相簿列表與照片分頁
- 上傳照片、建立相簿分類
- SQLite 資料庫，自動初始化
- 手機版響應式介面

## 安裝

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python app.py
```

開啟：

http://127.0.0.1:5000

## 預設管理員

- 帳號：`admin`
- 密碼：`admin123`

**正式使用前請立刻修改密碼。**

可用環境變數覆寫：

```bash
export BLOG_ADMIN_USER="yourname"
export BLOG_ADMIN_PASSWORD="your-strong-password"
export BLOG_SECRET_KEY="replace-with-a-long-random-value"
```

Windows PowerShell：

```powershell
$env:BLOG_ADMIN_USER="yourname"
$env:BLOG_ADMIN_PASSWORD="your-strong-password"
$env:BLOG_SECRET_KEY="replace-with-a-long-random-value"
python app.py
```

## 上傳限制

預設單張／單次請求上限約 12MB，允許：
PNG、JPG、JPEG、GIF、WEBP。

照片會放在：

`static/uploads/`

資料庫：

`blog.db`
