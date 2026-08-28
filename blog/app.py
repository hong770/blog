import os
import sqlite3
import uuid
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import (
    Flask, flash, redirect, render_template, request, session, url_for, abort
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
AVATAR_DIR = UPLOAD_DIR / "avatars"
AVATAR_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
POSTS_PER_PAGE = 5
PHOTOS_PER_PAGE = 8

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("BLOG_SECRET_KEY", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024

DB_PATH = BASE_DIR / "blog.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            category_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_published INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(category_id) REFERENCES categories(id)
        );

        CREATE TABLE IF NOT EXISTS albums (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            album_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            original_name TEXT NOT NULL,
            caption TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY(album_id) REFERENCES albums(id)
        );

        CREATE TABLE IF NOT EXISTS site_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            avatar_filename TEXT DEFAULT NULL
        );
        """
    )

    conn.execute("INSERT OR IGNORE INTO site_settings (id, avatar_filename) VALUES (1, NULL)")

    admin_user = os.environ.get("BLOG_ADMIN_USER", "admin")
    admin_password = os.environ.get("BLOG_ADMIN_PASSWORD", "admin123")
    existing_admin = conn.execute(
        "SELECT id FROM admins WHERE username = ?", (admin_user,)
    ).fetchone()

    if not existing_admin:
        conn.execute(
            "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
            (admin_user, generate_password_hash(admin_password)),
        )

    # Seed a few categories and an album for first run.
    if conn.execute("SELECT COUNT(*) AS c FROM categories").fetchone()["c"] == 0:
        conn.executemany(
            "INSERT INTO categories(name) VALUES (?)",
            [("日記",), ("生活",), ("心情",)],
        )

    if conn.execute("SELECT COUNT(*) AS c FROM albums").fetchone()["c"] == 0:
        conn.execute(
            "INSERT INTO albums(name, description) VALUES (?, ?)",
            ("生活隨拍", "把日常的小片段收進相簿裡。"),
        )

    if conn.execute("SELECT COUNT(*) AS c FROM posts").fetchone()["c"] == 0:
        cat = conn.execute("SELECT id FROM categories ORDER BY id LIMIT 1").fetchone()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        conn.execute(
            """INSERT INTO posts
               (title, content, category_id, created_at, updated_at, is_published)
               VALUES (?, ?, ?, ?, ?, 1)""",
            (
                "歡迎來到我的小站",
                "這裡是一個簡單、安靜的小角落。\n\n可以寫日記、整理文章，也可以把照片放進相簿。",
                cat["id"] if cat else None,
                now,
                now,
            ),
        )

    conn.commit()
    conn.close()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            flash("請先登入管理後台。", "warning")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def paginate(total, page, per_page):
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))
    offset = (page - 1) * per_page
    return page, pages, offset


@app.context_processor
def inject_globals():
    conn = get_db()
    categories = conn.execute(
        """
        SELECT c.id, c.name, COUNT(p.id) AS post_count
        FROM categories c
        LEFT JOIN posts p ON p.category_id = c.id AND p.is_published = 1
        GROUP BY c.id
        ORDER BY c.name
        """
    ).fetchall()
    albums = conn.execute(
        """
        SELECT a.id, a.name, COUNT(ph.id) AS photo_count
        FROM albums a
        LEFT JOIN photos ph ON ph.album_id = a.id
        GROUP BY a.id
        ORDER BY a.id DESC
        """
    ).fetchall()
    settings = conn.execute(
        "SELECT avatar_filename FROM site_settings WHERE id = 1"
    ).fetchone()
    avatar_filename = settings["avatar_filename"] if settings else None
    conn.close()
    return {
        "nav_categories": categories,
        "nav_albums": albums,
        "site_avatar": avatar_filename,
        "current_year": datetime.now().year,
    }


@app.route("/")
def index():
    page = request.args.get("page", 1, type=int)
    conn = get_db()
    total = conn.execute(
        "SELECT COUNT(*) AS c FROM posts WHERE is_published = 1"
    ).fetchone()["c"]
    page, pages, offset = paginate(total, page, POSTS_PER_PAGE)

    posts = conn.execute(
        """
        SELECT p.*, c.name AS category_name
        FROM posts p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.is_published = 1
        ORDER BY p.created_at DESC, p.id DESC
        LIMIT ? OFFSET ?
        """,
        (POSTS_PER_PAGE, offset),
    ).fetchall()
    conn.close()
    return render_template("index.html", posts=posts, page=page, pages=pages)


@app.route("/post/<int:post_id>")
def post_detail(post_id):
    conn = get_db()
    post = conn.execute(
        """
        SELECT p.*, c.name AS category_name
        FROM posts p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.id = ? AND p.is_published = 1
        """,
        (post_id,),
    ).fetchone()
    conn.close()
    if not post:
        abort(404)
    return render_template("post_detail.html", post=post)


@app.route("/category/<int:category_id>")
def category_view(category_id):
    page = request.args.get("page", 1, type=int)
    conn = get_db()
    category = conn.execute(
        "SELECT * FROM categories WHERE id = ?", (category_id,)
    ).fetchone()
    if not category:
        conn.close()
        abort(404)

    total = conn.execute(
        "SELECT COUNT(*) AS c FROM posts WHERE category_id = ? AND is_published = 1",
        (category_id,),
    ).fetchone()["c"]
    page, pages, offset = paginate(total, page, POSTS_PER_PAGE)

    posts = conn.execute(
        """
        SELECT p.*, c.name AS category_name
        FROM posts p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.category_id = ? AND p.is_published = 1
        ORDER BY p.created_at DESC, p.id DESC
        LIMIT ? OFFSET ?
        """,
        (category_id, POSTS_PER_PAGE, offset),
    ).fetchall()
    conn.close()
    return render_template(
        "category.html", category=category, posts=posts, page=page, pages=pages
    )


@app.route("/archive")
def archive():
    conn = get_db()
    posts = conn.execute(
        """
        SELECT p.id, p.title, p.created_at, c.name AS category_name
        FROM posts p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.is_published = 1
        ORDER BY p.created_at DESC, p.id DESC
        """
    ).fetchall()
    conn.close()
    return render_template("archive.html", posts=posts)


@app.route("/albums")
def albums():
    conn = get_db()
    albums_data = conn.execute(
        """
        SELECT a.*, COUNT(ph.id) AS photo_count,
               (
                 SELECT filename FROM photos p2
                 WHERE p2.album_id = a.id
                 ORDER BY p2.id DESC LIMIT 1
               ) AS cover
        FROM albums a
        LEFT JOIN photos ph ON ph.album_id = a.id
        GROUP BY a.id
        ORDER BY a.id DESC
        """
    ).fetchall()
    conn.close()
    return render_template("albums.html", albums=albums_data)


@app.route("/album/<int:album_id>")
def album_detail(album_id):
    page = request.args.get("page", 1, type=int)
    conn = get_db()
    album = conn.execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()
    if not album:
        conn.close()
        abort(404)

    total = conn.execute(
        "SELECT COUNT(*) AS c FROM photos WHERE album_id = ?", (album_id,)
    ).fetchone()["c"]
    page, pages, offset = paginate(total, page, PHOTOS_PER_PAGE)
    photos = conn.execute(
        """
        SELECT * FROM photos
        WHERE album_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        (album_id, PHOTOS_PER_PAGE, offset),
    ).fetchall()
    conn.close()
    return render_template(
        "album_detail.html", album=album, photos=photos, page=page, pages=pages
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin_id"):
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = get_db()
        admin = conn.execute(
            "SELECT * FROM admins WHERE username = ?", (username,)
        ).fetchone()
        conn.close()

        if admin and check_password_hash(admin["password_hash"], password):
            session.clear()
            session["admin_id"] = admin["id"]
            session["admin_username"] = admin["username"]
            flash("登入成功。", "success")
            next_url = request.args.get("next")
            return redirect(next_url or url_for("admin_dashboard"))

        flash("帳號或密碼錯誤。", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("已登出。", "info")
    return redirect(url_for("index"))


@app.route("/admin")
@login_required
def admin_dashboard():
    conn = get_db()
    counts = {
        "posts": conn.execute("SELECT COUNT(*) AS c FROM posts").fetchone()["c"],
        "categories": conn.execute("SELECT COUNT(*) AS c FROM categories").fetchone()["c"],
        "albums": conn.execute("SELECT COUNT(*) AS c FROM albums").fetchone()["c"],
        "photos": conn.execute("SELECT COUNT(*) AS c FROM photos").fetchone()["c"],
    }
    posts = conn.execute(
        """
        SELECT p.*, c.name AS category_name
        FROM posts p
        LEFT JOIN categories c ON c.id = p.category_id
        ORDER BY p.updated_at DESC, p.id DESC
        LIMIT 10
        """
    ).fetchall()
    conn.close()
    return render_template("admin_dashboard.html", counts=counts, posts=posts)


@app.route("/admin/profile", methods=["GET", "POST"])
@login_required
def admin_profile():
    conn = get_db()
    settings = conn.execute(
        "SELECT avatar_filename FROM site_settings WHERE id = 1"
    ).fetchone()
    current_avatar = settings["avatar_filename"] if settings else None

    if request.method == "POST":
        action = request.form.get("action", "upload")

        if action == "remove":
            if current_avatar:
                old_path = AVATAR_DIR / current_avatar
                if old_path.exists():
                    old_path.unlink()
            conn.execute(
                "UPDATE site_settings SET avatar_filename = NULL WHERE id = 1"
            )
            conn.commit()
            conn.close()
            flash("大頭貼已移除，已恢復預設圖示。", "info")
            return redirect(url_for("admin_profile"))

        avatar = request.files.get("avatar")
        if not avatar or not avatar.filename:
            flash("請先選擇圖片。", "warning")
        elif not allowed_file(avatar.filename):
            flash("只支援 PNG、JPG、JPEG、GIF、WEBP 圖片。", "danger")
        else:
            original = secure_filename(avatar.filename)
            ext = original.rsplit(".", 1)[1].lower()
            stored_name = f"avatar_{uuid.uuid4().hex}.{ext}"
            avatar.save(AVATAR_DIR / stored_name)

            if current_avatar:
                old_path = AVATAR_DIR / current_avatar
                if old_path.exists() and old_path.name != stored_name:
                    old_path.unlink()

            conn.execute(
                "UPDATE site_settings SET avatar_filename = ? WHERE id = 1",
                (stored_name,),
            )
            conn.commit()
            conn.close()
            flash("大頭貼已更新。", "success")
            return redirect(url_for("admin_profile"))

    conn.close()
    return render_template("admin_profile.html", current_avatar=current_avatar)


@app.route("/admin/posts")
@login_required
def admin_posts():
    conn = get_db()
    posts = conn.execute(
        """
        SELECT p.*, c.name AS category_name
        FROM posts p
        LEFT JOIN categories c ON c.id = p.category_id
        ORDER BY p.created_at DESC, p.id DESC
        """
    ).fetchall()
    conn.close()
    return render_template("admin_posts.html", posts=posts)


@app.route("/admin/post/new", methods=["GET", "POST"])
@login_required
def admin_post_new():
    conn = get_db()
    categories = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        category_id = request.form.get("category_id", type=int)
        is_published = 1 if request.form.get("is_published") else 0

        if not title or not content:
            flash("標題和內容不可空白。", "danger")
        else:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            conn.execute(
                """
                INSERT INTO posts
                (title, content, category_id, created_at, updated_at, is_published)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (title, content, category_id, now, now, is_published),
            )
            conn.commit()
            conn.close()
            flash("文章已建立。", "success")
            return redirect(url_for("admin_posts"))

    conn.close()
    return render_template("admin_post_form.html", post=None, categories=categories)


@app.route("/admin/post/<int:post_id>/edit", methods=["GET", "POST"])
@login_required
def admin_post_edit(post_id):
    conn = get_db()
    post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    if not post:
        conn.close()
        abort(404)
    categories = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        category_id = request.form.get("category_id", type=int)
        is_published = 1 if request.form.get("is_published") else 0

        if not title or not content:
            flash("標題和內容不可空白。", "danger")
        else:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            conn.execute(
                """
                UPDATE posts
                SET title = ?, content = ?, category_id = ?, updated_at = ?, is_published = ?
                WHERE id = ?
                """,
                (title, content, category_id, now, is_published, post_id),
            )
            conn.commit()
            conn.close()
            flash("文章已更新。", "success")
            return redirect(url_for("admin_posts"))

    conn.close()
    return render_template("admin_post_form.html", post=post, categories=categories)


@app.route("/admin/post/<int:post_id>/delete", methods=["POST"])
@login_required
def admin_post_delete(post_id):
    conn = get_db()
    conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    conn.commit()
    conn.close()
    flash("文章已刪除。", "info")
    return redirect(url_for("admin_posts"))


@app.route("/admin/categories", methods=["GET", "POST"])
@login_required
def admin_categories():
    conn = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("分類名稱不可空白。", "danger")
        else:
            try:
                conn.execute("INSERT INTO categories(name) VALUES (?)", (name,))
                conn.commit()
                flash("文章分類已新增。", "success")
            except sqlite3.IntegrityError:
                flash("此文章分類已存在。", "warning")

    categories = conn.execute(
        """
        SELECT c.*, COUNT(p.id) AS post_count
        FROM categories c
        LEFT JOIN posts p ON p.category_id = c.id
        GROUP BY c.id
        ORDER BY c.name
        """
    ).fetchall()
    conn.close()
    return render_template("admin_categories.html", categories=categories)


@app.route("/admin/albums", methods=["GET", "POST"])
@login_required
def admin_albums():
    conn = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        if not name:
            flash("相簿名稱不可空白。", "danger")
        else:
            try:
                conn.execute(
                    "INSERT INTO albums(name, description) VALUES (?, ?)",
                    (name, description),
                )
                conn.commit()
                flash("相簿分類已建立。", "success")
            except sqlite3.IntegrityError:
                flash("此相簿名稱已存在。", "warning")

    albums_data = conn.execute(
        """
        SELECT a.*, COUNT(ph.id) AS photo_count
        FROM albums a
        LEFT JOIN photos ph ON ph.album_id = a.id
        GROUP BY a.id
        ORDER BY a.id DESC
        """
    ).fetchall()
    conn.close()
    return render_template("admin_albums.html", albums=albums_data)


@app.route("/admin/photos", methods=["GET", "POST"])
@login_required
def admin_photos():
    conn = get_db()
    albums_data = conn.execute("SELECT * FROM albums ORDER BY name").fetchall()

    if request.method == "POST":
        album_id = request.form.get("album_id", type=int)
        caption = request.form.get("caption", "").strip()
        files = request.files.getlist("photos")

        album = conn.execute("SELECT id FROM albums WHERE id = ?", (album_id,)).fetchone()
        if not album:
            flash("請選擇有效的相簿分類。", "danger")
        else:
            uploaded = 0
            for file in files:
                if not file or not file.filename:
                    continue
                if not allowed_file(file.filename):
                    flash(f"{file.filename} 格式不支援。", "warning")
                    continue

                original = secure_filename(file.filename)
                ext = original.rsplit(".", 1)[1].lower()
                stored_name = f"{uuid.uuid4().hex}.{ext}"
                file.save(UPLOAD_DIR / stored_name)
                conn.execute(
                    """
                    INSERT INTO photos
                    (album_id, filename, original_name, caption, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        album_id,
                        stored_name,
                        original,
                        caption,
                        datetime.now().strftime("%Y-%m-%d %H:%M"),
                    ),
                )
                uploaded += 1

            conn.commit()
            if uploaded:
                flash(f"已上傳 {uploaded} 張照片。", "success")
            elif files:
                flash("沒有可上傳的照片。", "warning")

    photos = conn.execute(
        """
        SELECT ph.*, a.name AS album_name
        FROM photos ph
        JOIN albums a ON a.id = ph.album_id
        ORDER BY ph.id DESC
        LIMIT 40
        """
    ).fetchall()
    conn.close()
    return render_template(
        "admin_photos.html", albums=albums_data, photos=photos
    )


@app.route("/admin/photo/<int:photo_id>/delete", methods=["POST"])
@login_required
def admin_photo_delete(photo_id):
    conn = get_db()
    photo = conn.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
    if photo:
        file_path = UPLOAD_DIR / photo["filename"]
        if file_path.exists():
            file_path.unlink()
        conn.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
        conn.commit()
        flash("照片已刪除。", "info")
    conn.close()
    return redirect(url_for("admin_photos"))


@app.errorhandler(404)
def not_found(_):
    return render_template("404.html"), 404


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
