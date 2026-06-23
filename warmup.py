import random
import logging
from datetime import datetime, date, time as dt_time, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)


def is_account_warmed_up(account_id, db_session, WarmupSchedule):
    """Check if an account has completed today's warm-up.

    Args:
        account_id: The account ID to check.
        db_session: SQLAlchemy session.
        WarmupSchedule: The WarmupSchedule model class.

    Returns:
        True if the account is warmed up for today (or warm-up is disabled),
        False if warm-up is required but not yet completed.
    """
    schedule = WarmupSchedule.query.filter_by(account_id=account_id).first()
    if not schedule or not schedule.enabled:
        # No schedule or disabled = no warm-up required
        return True
    # Check if last_run_date is today
    today = date.today()
    return schedule.last_run_date == today


class WarmupEngine:
    """Background warm-up engine that runs daily warm-up routines for all accounts.

    Uses APScheduler's BackgroundScheduler to check every 5 minutes for pending
    warm-up actions. Each account gets a randomized daily plan with varied timing
    to simulate human-like behavior.
    """

    def __init__(self, app=None):
        """Initialize the WarmupEngine.

        Args:
            app: Flask application instance (optional, can be set later via init_app).
        """
        self.app = app
        self.scheduler = BackgroundScheduler()
        self._daily_plans = {}  # account_id -> list of planned actions for today

    def init_app(self, app):
        """Initialize with a Flask app.

        Args:
            app: Flask application instance.
        """
        self.app = app

    def start(self):
        """Start the background scheduler."""
        if not self.scheduler.running:
            self.scheduler.add_job(
                self._check_warmup_tasks,
                'interval',
                minutes=5,
                id='warmup_check',
                replace_existing=True,
                next_run_time=datetime.now() + timedelta(seconds=30)
            )
            self.scheduler.start()
            logger.info("WarmupEngine scheduler started")

    def shutdown(self):
        """Shut down the background scheduler gracefully."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("WarmupEngine scheduler shut down")

    def _check_warmup_tasks(self):
        """Periodic task that checks for pending warm-up actions and executes them."""
        if not self.app:
            return

        with self.app.app_context():
            try:
                from app import db, Account, WarmupSchedule, WarmupLog
                today = date.today()
                now = datetime.now()

                # Get all accounts with enabled warm-up schedules
                schedules = WarmupSchedule.query.filter_by(enabled=True).all()

                for schedule in schedules:
                    account = db.session.get(Account, schedule.account_id)
                    if not account:
                        continue

                    # Check if already completed today
                    if schedule.last_run_date == today:
                        continue

                    # Check if within time window
                    try:
                        start_parts = schedule.time_window_start.split(':')
                        end_parts = schedule.time_window_end.split(':')
                        window_start = dt_time(int(start_parts[0]), int(start_parts[1]))
                        window_end = dt_time(int(end_parts[0]), int(end_parts[1]))
                    except (ValueError, IndexError):
                        window_start = dt_time(8, 0)
                        window_end = dt_time(22, 0)

                    current_time = now.time()
                    if current_time < window_start or current_time > window_end:
                        continue

                    # Generate and execute daily plan for this account
                    plan = self._get_or_create_daily_plan(schedule)
                    self._execute_plan(account, schedule, plan)

            except Exception as e:
                logger.exception("WarmupEngine check failed: %s", str(e))

    def _get_or_create_daily_plan(self, schedule):
        """Get or create a randomized daily plan for an account.

        Args:
            schedule: WarmupSchedule instance.

        Returns:
            List of action dicts with type and execution info.
        """
        today = date.today()
        plan_key = f"{schedule.account_id}_{today.isoformat()}"

        if plan_key in self._daily_plans:
            return self._daily_plans[plan_key]

        # Generate randomized counts for each action type
        watch_count = random.randint(schedule.daily_watch_min, schedule.daily_watch_max)
        like_count = random.randint(schedule.daily_like_min, schedule.daily_like_max)
        comment_count = random.randint(schedule.daily_comment_min, schedule.daily_comment_max)
        follow_count = random.randint(schedule.daily_follow_min, schedule.daily_follow_max)

        plan = []
        for _ in range(watch_count):
            plan.append({"type": "watch"})
        for _ in range(like_count):
            plan.append({"type": "like"})
        for _ in range(comment_count):
            plan.append({"type": "comment"})
        for _ in range(follow_count):
            plan.append({"type": "follow"})

        # Shuffle for randomized ordering
        random.shuffle(plan)

        self._daily_plans[plan_key] = plan
        return plan

    def _execute_plan(self, account, schedule, plan):
        """Execute the warm-up plan for an account.

        Args:
            account: Account instance.
            schedule: WarmupSchedule instance.
            plan: List of action dicts to execute.
        """
        from app import db, WarmupLog
        import time as time_module

        if not plan:
            # No actions - mark as complete
            schedule.last_run_date = date.today()
            db.session.commit()
            return

        try:
            if account.platform == "tiktok":
                self._execute_tiktok_plan(account, schedule, plan)
            elif account.platform == "facebook":
                self._execute_facebook_plan(account, schedule, plan)

            # Mark today's warm-up as complete
            schedule.last_run_date = date.today()
            schedule.updated_at = datetime.utcnow()
            db.session.commit()

            # Clean up the plan from memory
            today = date.today()
            plan_key = f"{schedule.account_id}_{today.isoformat()}"
            self._daily_plans.pop(plan_key, None)

        except Exception as e:
            logger.exception(
                "Warmup execution failed for account %s: %s",
                account.id, str(e)
            )

    def _execute_tiktok_plan(self, account, schedule, plan):
        """Execute warm-up actions for a TikTok account.

        Args:
            account: Account instance (TikTok).
            schedule: WarmupSchedule instance.
            plan: List of action dicts.
        """
        from app import db, WarmupLog
        from main import TikTok
        import time as time_module

        proxy = account.proxy if account.proxy else None
        tiktok = TikTok(account.session_id, proxy=proxy)

        # Get feed videos for targeting
        targets = tiktok.get_feed()
        if not targets:
            # Try the older get_video method as fallback
            targets = tiktok.get_video()

        if not targets:
            logger.warning("No targets found for TikTok account %s", account.id)
            # Log a skipped entry
            log_entry = WarmupLog(
                account_id=account.id,
                action_type="watch",
                target_id="",
                status="skipped",
                detail="No feed targets available",
                executed_at=datetime.utcnow()
            )
            db.session.add(log_entry)
            db.session.commit()
            return

        for action in plan:
            target = random.choice(targets)
            status = "failed"
            detail = ""

            try:
                if action["type"] == "watch":
                    success = tiktok.watch_video(target)
                    status = "success" if success else "failed"
                    detail = f"Watched video {target}"
                elif action["type"] == "like":
                    success = tiktok.like_video(target)
                    status = "success" if success else "failed"
                    detail = f"Liked video {target}"
                elif action["type"] == "comment":
                    # Use a simple warm-up comment
                    warmup_comments = ["nice!", "love this", "awesome", "great video", "cool"]
                    comment_text = random.choice(warmup_comments)
                    success = tiktok.send(comment_text, target)
                    status = "success" if success is True else "failed"
                    detail = f"Comment: {comment_text}"
                elif action["type"] == "follow":
                    # For follow, we would need user IDs from the feed
                    # Using target as a placeholder - in practice this would be a user_id
                    success = tiktok.follow_user(target)
                    status = "success" if success else "failed"
                    detail = f"Followed user from video {target}"
            except Exception as e:
                status = "failed"
                detail = str(e)[:200]

            log_entry = WarmupLog(
                account_id=account.id,
                action_type=action["type"],
                target_id=target,
                status=status,
                detail=detail,
                executed_at=datetime.utcnow()
            )
            db.session.add(log_entry)
            db.session.commit()

            # Random delay between actions (5-30 seconds) for human-like behavior
            time_module.sleep(random.randint(5, 30))

    def _execute_facebook_plan(self, account, schedule, plan):
        """Execute warm-up actions for a Facebook account.

        Args:
            account: Account instance (Facebook).
            schedule: WarmupSchedule instance.
            plan: List of action dicts.
        """
        from app import db, WarmupLog
        from facebook import Facebook
        import time as time_module

        proxy = account.proxy if account.proxy else None
        fb = Facebook(account.session_id, proxy=proxy)

        # Get feed posts for targeting
        targets = fb.get_feed()

        if not targets:
            logger.warning("No targets found for Facebook account %s", account.id)
            log_entry = WarmupLog(
                account_id=account.id,
                action_type="watch",
                target_id="",
                status="skipped",
                detail="No feed targets available",
                executed_at=datetime.utcnow()
            )
            db.session.add(log_entry)
            db.session.commit()
            return

        for action in plan:
            target = random.choice(targets)
            status = "failed"
            detail = ""

            try:
                if action["type"] == "watch":
                    success = fb.watch_video(target)
                    status = "success" if success else "failed"
                    detail = f"Viewed post {target}"
                elif action["type"] == "like":
                    success = fb.like_post(target)
                    status = "success" if success else "failed"
                    detail = f"Liked post {target}"
                elif action["type"] == "comment":
                    warmup_comments = ["nice!", "love this", "awesome", "great post", "cool"]
                    comment_text = random.choice(warmup_comments)
                    success = fb.comment_post(target, comment_text)
                    status = "success" if success else "failed"
                    detail = f"Comment: {comment_text}"
                elif action["type"] == "follow":
                    success = fb.follow_user(target)
                    status = "success" if success else "failed"
                    detail = f"Followed user from post {target}"
            except Exception as e:
                status = "failed"
                detail = str(e)[:200]

            log_entry = WarmupLog(
                account_id=account.id,
                action_type=action["type"],
                target_id=target,
                status=status,
                detail=detail,
                executed_at=datetime.utcnow()
            )
            db.session.add(log_entry)
            db.session.commit()

            # Random delay between actions (5-30 seconds) for human-like behavior
            time_module.sleep(random.randint(5, 30))

    def run_now(self, account_id):
        """Manually trigger a warm-up run for a specific account.

        Args:
            account_id: The account ID to run warm-up for.

        Returns:
            True if the warm-up was triggered, False otherwise.
        """
        if not self.app:
            return False

        with self.app.app_context():
            try:
                from app import db, Account, WarmupSchedule

                schedule = WarmupSchedule.query.filter_by(account_id=account_id).first()
                if not schedule:
                    return False

                account = db.session.get(Account, account_id)
                if not account:
                    return False

                # Reset last_run_date to force re-run
                schedule.last_run_date = None
                db.session.commit()

                # Generate and execute plan
                plan = self._get_or_create_daily_plan(schedule)
                self._execute_plan(account, schedule, plan)
                return True

            except Exception as e:
                logger.exception("Manual warmup run failed for account %s: %s", account_id, str(e))
                return False


# Global engine instance
warmup_engine = WarmupEngine()
