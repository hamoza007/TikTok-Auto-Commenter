import os
import re
import logging
import threading
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
logger = logging.getLogger(__name__)


class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nickname = db.Column(db.String(100), nullable=False)
    session_id = db.Column(db.String(255), nullable=False)
    proxy = db.Column(db.String(255), default="")
    platform = db.Column(db.String(50), default="tiktok")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    video_url = db.Column(db.String(500), nullable=False)
    aweme_id = db.Column(db.String(100), default="")
    prompt = db.Column(db.Text, default="")
    platform = db.Column(db.String(50), default="tiktok")
    status = db.Column(db.String(50), default="pending")
    error_message = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    comments = db.relationship("ProjectComment", backref="project", lazy=True, cascade="all, delete-orphan")
    history_entries = db.relationship("History", backref="project", lazy=True, cascade="all, delete-orphan")


class ProjectComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    comment_text = db.Column(db.Text, default="")
    status = db.Column(db.String(50), default="pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    account = db.relationship("Account", backref="project_comments", lazy=True)


class History(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    video_id = db.Column(db.String(100), default="")
    comment_text = db.Column(db.Text, default="")
    status = db.Column(db.String(50), default="success")
    account_nickname = db.Column(db.String(100), default="")
    video_url = db.Column(db.String(500), default="")
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


class GlobalSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, default="")


def get_global_setting(key):
    """Get a global setting value by key. Returns None if not found."""
    setting = GlobalSettings.query.filter_by(key=key).first()
    return setting.value if setting else None


def set_global_setting(key, value):
    """Set a global setting value (upsert). Creates if not exists, updates if exists."""
    setting = GlobalSettings.query.filter_by(key=key).first()
    if setting:
        setting.value = value
    else:
        setting = GlobalSettings(key=key, value=value)
        db.session.add(setting)
    db.session.commit()


def extract_aweme_id(video_url):
    """Extract aweme_id from a TikTok video URL or return the URL if it looks like an ID.

    Returns a numeric string aweme_id, or None if extraction fails.
    """
    match = re.search(r'/video/(\d+)', video_url)
    if match:
        return match.group(1)
    if video_url.strip().isdigit():
        return video_url.strip()
    return None


def generate_comment_with_openai(api_key, prompt, video_url, count=1):
    """Use OpenAI to generate unique comments based on a prompt/theme description.

    Args:
        api_key: OpenAI API key
        prompt: Theme description or prompt for generating comments
        video_url: The video URL for context
        count: Number of unique comments to generate

    Returns:
        A list of generated comment strings, or empty list on failure.
    """
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        model = get_global_setting("openai_model") or "gpt-3.5-turbo"
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that generates short, engaging TikTok comments."
                },
                {
                    "role": "user",
                    "content": (
                        f"Based on this theme/prompt: '{prompt}', "
                        f"for this video: {video_url}, "
                        f"generate exactly {count} unique and engaging TikTok comments. "
                        f"Each comment should be different, short (under 100 characters), natural, and friendly. "
                        f"Return each comment on its own line, numbered like:\n"
                        f"1. comment here\n2. comment here\n"
                        f"Do not include any other text."
                    )
                }
            ],
            max_tokens=count * 80,
            temperature=0.9
        )
        raw = response.choices[0].message.content.strip()
        # Parse numbered list
        lines = raw.split("\n")
        comments = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Remove numbering prefix like "1. " or "1) "
            cleaned = re.sub(r'^\d+[\.\)]\s*', '', line)
            if cleaned:
                comments.append(cleaned)
        return comments[:count]
    except Exception as e:
        logger.exception("Failed to generate comments with OpenAI: %s", str(e))
        return []


def run_project_task(app, project_id):
    """Background task to run a project's commenting workflow using multi-account ProjectComments."""
    with app.app_context():
        project = db.session.get(Project, project_id)
        if not project:
            return

        try:
            from main import TikTok
            import time

            aweme_id = extract_aweme_id(project.video_url)

            # Validate aweme_id is numeric
            if aweme_id is None:
                error_msg = (
                    f"Could not extract a valid numeric aweme_id from URL: "
                    f"{project.video_url}"
                )
                logger.error(error_msg)
                project.status = "failed"
                project.error_message = error_msg
                db.session.commit()
                return

            if not project.aweme_id:
                project.aweme_id = aweme_id
                db.session.commit()

            # Get all pending comments for this project
            pending_comments = ProjectComment.query.filter_by(
                project_id=project.id, status="pending"
            ).all()

            if not pending_comments:
                project.status = "completed"
                project.error_message = "No pending comments to send"
                db.session.commit()
                return

            for pc in pending_comments:
                account = db.session.get(Account, pc.account_id)
                if not account:
                    pc.status = "failed"
                    history_entry = History(
                        project_id=project.id,
                        video_id=aweme_id,
                        comment_text=pc.comment_text,
                        status="failed",
                        account_nickname="Unknown (deleted)",
                        video_url=project.video_url,
                        timestamp=datetime.utcnow()
                    )
                    db.session.add(history_entry)
                    db.session.commit()
                    continue

                # Pass proxy from account to TikTok class
                proxy = account.proxy if account.proxy else None
                tiktok = TikTok(account.session_id, proxy=proxy)

                result = tiktok.send(pc.comment_text, aweme_id)

                if result is True:
                    status = "success"
                elif result == "Spam":
                    status = "spam"
                else:
                    status = "failed"

                pc.status = status

                history_entry = History(
                    project_id=project.id,
                    video_id=aweme_id,
                    comment_text=pc.comment_text,
                    status=status,
                    account_nickname=account.nickname,
                    video_url=project.video_url,
                    timestamp=datetime.utcnow()
                )
                db.session.add(history_entry)
                db.session.commit()

                if status == "spam":
                    time.sleep(10)

            project.status = "completed"
            db.session.commit()

        except Exception as e:
            logger.exception("Project %s failed with error: %s", project_id, str(e))
            # Refresh the session in case it's in a bad state from the exception
            db.session.rollback()
            project = db.session.get(Project, project_id)
            if project:
                project.status = "failed"
                project.error_message = str(e)[:500]
                db.session.commit()


def create_app():
    app = Flask(__name__)

    # Generate a random secret key if not set via environment variable.
    # This ensures session cookies are not forgeable even in development.
    secret_key = os.environ.get("SECRET_KEY")
    if not secret_key:
        secret_key = os.urandom(24).hex()
        logger.warning(
            "SECRET_KEY not set in environment. Generated a random key. "
            "Sessions will not persist across restarts."
        )
    app.config["SECRET_KEY"] = secret_key

    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///tiktok_dashboard.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    # Enable connection health checks to detect stale connections before use
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
    }

    db.init_app(app)

    with app.app_context():
        db.create_all()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # TODO: Add CSRF protection (e.g., Flask-WTF) for all state-mutating POST routes
    # TODO: Consider application-level encryption for credentials (session_id, openai_api_key) at rest

    # --- Settings Routes ---
    @app.route("/settings")
    def settings():
        accounts = Account.query.order_by(Account.created_at.desc()).all()
        openai_api_key = get_global_setting("openai_api_key") or ""
        openai_model = get_global_setting("openai_model") or ""
        return render_template(
            "settings.html",
            accounts=accounts,
            openai_api_key=openai_api_key,
            openai_model=openai_model
        )

    @app.route("/settings/add", methods=["POST"])
    def settings_add():
        nickname = request.form.get("nickname", "").strip()
        session_id = request.form.get("session_id", "").strip()
        proxy = request.form.get("proxy", "").strip()
        platform = request.form.get("platform", "tiktok").strip()

        if not nickname or not session_id:
            flash("Nickname and Session ID are required.", "error")
            return redirect(url_for("settings"))

        if platform not in ("tiktok", "facebook"):
            platform = "tiktok"

        account = Account(
            nickname=nickname,
            session_id=session_id,
            proxy=proxy,
            platform=platform
        )
        db.session.add(account)
        db.session.commit()
        flash("Account added successfully.", "success")
        return redirect(url_for("settings"))

    @app.route("/settings/edit/<int:id>", methods=["POST"])
    def settings_edit(id):
        account = db.session.get(Account, id)
        if not account:
            flash("Account not found.", "error")
            return redirect(url_for("settings"))

        account.nickname = request.form.get("nickname", account.nickname).strip()
        # Only update credentials if a new value is provided (blank means keep existing)
        new_session_id = request.form.get("session_id", "").strip()
        if new_session_id:
            account.session_id = new_session_id
        account.proxy = request.form.get("proxy", "").strip()
        platform = request.form.get("platform", account.platform).strip()
        if platform in ("tiktok", "facebook"):
            account.platform = platform
        account.updated_at = datetime.utcnow()

        db.session.commit()
        flash("Account updated successfully.", "success")
        return redirect(url_for("settings"))

    @app.route("/settings/delete/<int:id>", methods=["POST"])
    def settings_delete(id):
        account = db.session.get(Account, id)
        if not account:
            flash("Account not found.", "error")
            return redirect(url_for("settings"))

        db.session.delete(account)
        db.session.commit()
        flash("Account deleted successfully.", "success")
        return redirect(url_for("settings"))

    @app.route("/settings/global", methods=["POST"])
    def settings_global():
        openai_api_key = request.form.get("openai_api_key", "").strip()
        openai_model = request.form.get("openai_model", "").strip()

        set_global_setting("openai_api_key", openai_api_key)
        set_global_setting("openai_model", openai_model)

        flash("Global AI settings saved successfully.", "success")
        return redirect(url_for("settings"))

    @app.route("/settings/api/models")
    def settings_api_models():
        api_key = request.args.get("api_key", "").strip()
        if not api_key:
            api_key = get_global_setting("openai_api_key") or ""

        if not api_key:
            return jsonify({"error": "No API key provided", "models": []}), 200

        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            models_response = client.models.list()
            model_ids = sorted([
                m.id for m in models_response.data
                if m.id.startswith("gpt-")
            ])
            return jsonify({"models": model_ids})
        except Exception as e:
            return jsonify({"error": str(e), "models": []}), 200

    # --- Dashboard Routes ---
    @app.route("/")
    @app.route("/dashboard")
    def dashboard():
        projects = Project.query.filter_by(platform="tiktok").order_by(Project.created_at.desc()).all()
        accounts = Account.query.filter_by(platform="tiktok").all()
        return render_template("dashboard.html", projects=projects, accounts=accounts)

    @app.route("/projects/generate-comments", methods=["POST"])
    def projects_generate_comments():
        """Generate AI comments for all TikTok accounts based on a prompt."""
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON request"}), 400

        name = (data.get("name") or "").strip()
        video_url = (data.get("video_url") or "").strip()
        prompt = (data.get("prompt") or "").strip()

        if not name or not video_url or not prompt:
            return jsonify({"error": "Name, video URL, and prompt are required"}), 400

        # Get all TikTok accounts
        tiktok_accounts = Account.query.filter_by(platform="tiktok").all()
        if not tiktok_accounts:
            return jsonify({"error": "No TikTok accounts found. Add accounts in Settings first."}), 400

        count = len(tiktok_accounts)

        # Get global OpenAI API key
        api_key = get_global_setting("openai_api_key")
        if not api_key:
            return jsonify({"error": "OpenAI API key not configured. Set it in Settings."}), 400

        # Generate comments
        comments = generate_comment_with_openai(api_key, prompt, video_url, count=count)

        # If generation failed or returned fewer comments, fill with prompt-based defaults
        while len(comments) < count:
            comments.append(f"{prompt} #{len(comments) + 1}")

        # Build response with account assignments
        result = []
        for i, account in enumerate(tiktok_accounts):
            result.append({
                "account_id": account.id,
                "account_nickname": account.nickname,
                "comment_text": comments[i]
            })

        return jsonify({"comments": result})

    @app.route("/projects/create-with-comments", methods=["POST"])
    def projects_create_with_comments():
        """Create a project with pre-generated per-account comments."""
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON request"}), 400

        name = (data.get("name") or "").strip()
        video_url = (data.get("video_url") or "").strip()
        prompt = (data.get("prompt") or "").strip()
        comments_data = data.get("comments", [])

        if not name or not video_url or not prompt:
            return jsonify({"error": "Name, video URL, and prompt are required"}), 400

        if not comments_data:
            return jsonify({"error": "At least one comment is required"}), 400

        aweme_id = extract_aweme_id(video_url)

        project = Project(
            name=name,
            video_url=video_url,
            aweme_id=aweme_id or "",
            prompt=prompt,
            platform="tiktok",
            status="pending"
        )
        db.session.add(project)
        db.session.flush()  # Get the project ID

        for item in comments_data:
            account_id = item.get("account_id")
            comment_text = (item.get("comment_text") or "").strip()
            if account_id and comment_text:
                pc = ProjectComment(
                    project_id=project.id,
                    account_id=int(account_id),
                    comment_text=comment_text,
                    status="pending"
                )
                db.session.add(pc)

        db.session.commit()
        return jsonify({"success": True, "project_id": project.id})

    @app.route("/projects/run/<int:id>", methods=["POST"])
    def projects_run(id):
        project = db.session.get(Project, id)
        if not project:
            flash("Project not found.", "error")
            return redirect(url_for("dashboard"))

        if project.status == "running":
            flash("Project is already running.", "warning")
            return redirect(url_for("dashboard"))

        # Set status to "running" and commit before spawning the thread to prevent
        # duplicate execution from concurrent requests (e.g., double-clicks).
        project.status = "running"
        db.session.commit()

        # TODO: Add thread timeout/cancellation mechanism and limit concurrent threads
        thread = threading.Thread(target=run_project_task, args=(app, project.id))
        thread.daemon = True
        thread.start()

        flash("Project started running in the background.", "success")
        return redirect(url_for("dashboard"))

    # --- History Routes ---
    @app.route("/history")
    def history():
        entries = History.query.order_by(History.timestamp.desc()).all()
        return render_template("history.html", entries=entries)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000)
