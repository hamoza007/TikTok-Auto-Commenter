import json
import logging
import time
import re

import requests

logger = logging.getLogger(__name__)


class Facebook:
    """Facebook class using cookie-based authentication (c_user + xs cookies).

    Each instance creates its own isolated requests.Session with separate cookies
    and proxy configuration to prevent cross-contamination between accounts.
    """

    def __init__(self, cookies_json: str, proxy: str = None) -> None:
        """Initialize Facebook instance with cookie-based auth.

        Args:
            cookies_json: JSON string containing Facebook cookies.
                          Format: {"c_user": "...", "xs": "..."}
            proxy: Optional proxy URL (e.g., http://host:port)
        """
        self.cookies = self._parse_cookies(cookies_json)
        self.session = requests.Session()

        # Set cookies on the session's cookie jar
        for name, value in self.cookies.items():
            self.session.cookies.set(name, value, domain=".facebook.com")

        # Set common headers to mimic a mobile browser
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 12; SM-G991B) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/112.0.0.0 Mobile Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })

        # Set proxy configuration
        if proxy:
            self.session.proxies = {
                "http": proxy,
                "https": proxy,
            }

    def _parse_cookies(self, cookies_json: str) -> dict:
        """Parse cookies from JSON string.

        Args:
            cookies_json: JSON string with c_user and xs keys.

        Returns:
            Dictionary of cookie name-value pairs.

        Raises:
            Warning log if cookies are empty or missing required keys.
        """
        try:
            cookies = json.loads(cookies_json)
            if not isinstance(cookies, dict):
                logger.warning("Cookies JSON is not a dict, using empty cookies")
                return {}
            # Validate required cookie keys
            if not cookies.get("c_user") or not cookies.get("xs"):
                logger.warning(
                    "Facebook cookies missing required keys (c_user, xs). "
                    "Account will be skipped during warm-up."
                )
                return {}
            return cookies
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(
                "Failed to parse cookies JSON: %s. "
                "Account will be skipped during warm-up.", str(e)
            )
            return {}

    @property
    def has_valid_cookies(self) -> bool:
        """Check if this Facebook instance has valid (non-empty) cookies.

        Returns:
            True if cookies were parsed successfully and contain required keys.
        """
        return bool(self.cookies and self.cookies.get("c_user") and self.cookies.get("xs"))

    def watch_video(self, post_id: str) -> bool:
        """Simulate watching a video/post by fetching its page.

        Args:
            post_id: The Facebook post or video ID.

        Returns:
            True if the page was fetched successfully, False otherwise.
        """
        try:
            url = f"https://mbasic.facebook.com/story.php?story_fbid={post_id}"
            response = self.session.get(url, timeout=15)
            # Simulate watch time
            time.sleep(2 + (hash(post_id) % 3))
            return response.status_code == 200
        except Exception as e:
            logger.error("Facebook watch_video failed for %s: %s", post_id, str(e))
            return False

    def like_post(self, post_id: str) -> bool:
        """Like a Facebook post via mbasic.

        Args:
            post_id: The Facebook post ID to like.

        Returns:
            True if the like was successful, False otherwise.
        """
        try:
            # First fetch the post page to get the like action URL
            url = f"https://mbasic.facebook.com/story.php?story_fbid={post_id}"
            response = self.session.get(url, timeout=15)
            if response.status_code != 200:
                return False

            # Look for the like action link in mbasic HTML
            like_match = re.search(
                r'href="(/a/like\.php\?[^"]+)"',
                response.text
            )
            if like_match:
                like_url = f"https://mbasic.facebook.com{like_match.group(1)}"
                like_response = self.session.get(like_url, timeout=15)
                return like_response.status_code == 200

            return False
        except Exception as e:
            logger.error("Facebook like_post failed for %s: %s", post_id, str(e))
            return False

    def comment_post(self, post_id: str, text: str) -> bool:
        """Post a comment on a Facebook post via mbasic.

        Args:
            post_id: The Facebook post ID to comment on.
            text: The comment text.

        Returns:
            True if the comment was posted successfully, False otherwise.
        """
        try:
            url = f"https://mbasic.facebook.com/story.php?story_fbid={post_id}"
            response = self.session.get(url, timeout=15)
            if response.status_code != 200:
                return False

            # Find the comment form action URL
            form_match = re.search(
                r'action="(/a/comment\.php\?[^"]+)"',
                response.text
            )
            if form_match:
                comment_url = f"https://mbasic.facebook.com{form_match.group(1)}"
                data = {"comment_text": text}
                post_response = self.session.post(comment_url, data=data, timeout=15)
                return post_response.status_code in (200, 301, 302)

            return False
        except Exception as e:
            logger.error("Facebook comment_post failed for %s: %s", post_id, str(e))
            return False

    def follow_user(self, user_id: str) -> bool:
        """Follow a Facebook user.

        Args:
            user_id: The Facebook user ID or username to follow.

        Returns:
            True if the follow was successful, False otherwise.
        """
        try:
            url = f"https://mbasic.facebook.com/{user_id}"
            response = self.session.get(url, timeout=15)
            if response.status_code != 200:
                return False

            # Look for follow/subscribe action
            follow_match = re.search(
                r'href="(/a/subscribe\.php\?[^"]+)"',
                response.text
            )
            if follow_match:
                follow_url = f"https://mbasic.facebook.com{follow_match.group(1)}"
                follow_response = self.session.get(follow_url, timeout=15)
                return follow_response.status_code == 200

            return False
        except Exception as e:
            logger.error("Facebook follow_user failed for %s: %s", user_id, str(e))
            return False

    def get_feed(self) -> list:
        """Fetch recent public posts from the Facebook feed.

        Returns:
            A list of post IDs from the feed for use as warm-up targets.
        """
        try:
            url = "https://mbasic.facebook.com/home.php"
            response = self.session.get(url, timeout=15)
            if response.status_code != 200:
                return []

            # Extract post/story IDs from mbasic feed
            post_ids = re.findall(
                r'story_fbid=(\d+)',
                response.text
            )
            # Return unique IDs
            return list(set(post_ids))[:20]
        except Exception as e:
            logger.error("Facebook get_feed failed: %s", str(e))
            return []

    def send(self, comment: str, post_url: str) -> bool:
        """Send a comment to a Facebook post (legacy interface).

        Args:
            comment: The comment text to post.
            post_url: The URL of the Facebook post to comment on.

        Returns:
            True if the comment was posted, False otherwise.
        """
        # Extract post ID from URL
        post_id_match = re.search(r'story_fbid=(\d+)', post_url)
        if not post_id_match:
            # Try other URL formats
            post_id_match = re.search(r'/posts/(\d+)', post_url)
        if not post_id_match:
            post_id_match = re.search(r'/(\d+)/?$', post_url)

        if post_id_match:
            return self.comment_post(post_id_match.group(1), comment)

        return False
