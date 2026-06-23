import os
import re
import threading
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nickname = db.Column(db.String(100), nullable=False)
    session_id = db.Column(db.String(255), nullable=False)
    proxy = db.Column(db.String(255), default="")
    openai_api_key = db.Column(db.String(255), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    projects = db.relationship("Project", backref="account", lazy=True, cascade="all, delete-orphan")


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    video_url = db.Column(db.String(500), nullable=False)
    aweme_id = db.Column(db.String(100), default="")
    comment_template = db.Column(db.Text, nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    status = db.Column(db.String(50), default="pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    history_entries = db.relationship("History", backref="project", lazy=True, cascade="all, delete-orphan")


class History(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    video_id = db.Column(db.String(100), default="")
    comment_text = db.Column(db.Text, default="")
    status = db.Column(db.String(50), default="success")
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


def extract_aweme_id(video_url):
    """Extract aweme_id from a TikTok video URL or return the URL if it looks like an ID."""
    match = re.search(r'/video/(\d+)', video_url)
    if match:
        return match.group(1)
    if video_url.strip().isdigit():
        return video_url.strip()
    return video_url.strip()


def generate_comment_with_openai(api_key, template, video_url):
    """Use OpenAI to generate a contextual comment based on the template."""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that generates short, engaging TikTok comments."
                },
                {
                    "role": "user",
                    "content": (
                        f"Based on this comment template: '{template}', "
                        f"generate a unique and engaging TikTok comment. "
                        f"Keep it short (under 100 characters), natural, and friendly."
                    )
                }
            ],
            max_tokens=60,
            temperature=0.8
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return None


def run_project_task(app, project_id):
    """Background task to run a project's commenting workflow."""
    with app.app_context():
        project = db.session.get(Project, project_id)
        if not project:
            return

        project.status = "running"
        db.session.commit()

        try:
            from main import TikTok

            account = db.session.get(Account, project.account_id)
            if not account:
                project.status = "failed"
                db.session.commit()
                return

            tiktok = TikTok(account.session_id)
            aweme_id = extract_aweme_id(project.video_url)
            if not project.aweme_id:
                project.aweme_id = aweme_id
                db.session.commit()

            comments = [c.strip() for c in project.comment_template.split("\n") if c.strip()]
            if not comments:
                comments = [project.comment_template]

            import random

            for comment_text in comments:
                # If account has OpenAI key, try to generate a contextual comment
                if account.openai_api_key:
                    generated = generate_comment_with_openai(
                        account.openai_api_key, comment_text, project.video_url
                    )
                    if generated:
                        comment_text = generated

                result = tiktok.send(comment_text, aweme_id)

                if result is True:
                    status = "success"
                elif result == "Spam":
                    status = "spam"
                else:
                    status = "failed"

                history_entry = History(
                    project_id=project.id,
                    video_id=aweme_id,
                    comment_text=comment_text,
                    status=status,
                    timestamp=datetime.utcnow()
                )
                db.session.add(history_entry)
                db.session.commit()

                if status == "spam":
                    import time
                    time.sleep(10)

            project.status = "completed"
            db.session.commit()

        except Exception as e:
            project.status = "failed"
            db.session.commit()


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///tiktok_dashboard.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    with app.app_context():
        db.create_all()

    # --- Settings Routes ---
    @app.route("/settings")
    def settings():
        accounts = Account.query.order_by(Account.created_at.desc()).all()
        return render_template("settings.html", accounts=accounts)

    @app.route("/settings/add", methods=["POST"])
    def settings_add():
        nickname = request.form.get("nickname", "").strip()
        session_id = request.form.get("session_id", "").strip()
        proxy = request.form.get("proxy", "").strip()
        openai_api_key = request.form.get("openai_api_key", "").strip()

        if not nickname or not session_id:
            flash("Nickname and Session ID are required.", "error")
            return redirect(url_for("settings"))

        account = Account(
            nickname=nickname,
            session_id=session_id,
            proxy=proxy,
            openai_api_key=openai_api_key
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
        account.session_id = request.form.get("session_id", account.session_id).strip()
        account.proxy = request.form.get("proxy", "").strip()
        account.openai_api_key = request.form.get("openai_api_key", "").strip()
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

    # --- Dashboard Routes ---
    @app.route("/")
    @app.route("/dashboard")
    def dashboard():
        projects = Project.query.order_by(Project.created_at.desc()).all()
        accounts = Account.query.all()
        return render_template("dashboard.html", projects=projects, accounts=accounts)

    @app.route("/projects/create", methods=["POST"])
    def projects_create():
        name = request.form.get("name", "").strip()
        video_url = request.form.get("video_url", "").strip()
        comment_template = request.form.get("comment_template", "").strip()
        account_id = request.form.get("account_id", "")

        if not name or not video_url or not comment_template or not account_id:
            flash("All fields are required.", "error")
            return redirect(url_for("dashboard"))

        aweme_id = extract_aweme_id(video_url)

        project = Project(
            name=name,
            video_url=video_url,
            aweme_id=aweme_id,
            comment_template=comment_template,
            account_id=int(account_id),
            status="pending"
        )
        db.session.add(project)
        db.session.commit()
        flash("Project created successfully.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/projects/run/<int:id>", methods=["POST"])
    def projects_run(id):
        project = db.session.get(Project, id)
        if not project:
            flash("Project not found.", "error")
            return redirect(url_for("dashboard"))

        if project.status == "running":
            flash("Project is already running.", "warning")
            return redirect(url_for("dashboard"))

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
