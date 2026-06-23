import requests, random, binascii, os, uuid, time, re, json
from typing import Union
from urllib.parse import urlencode
from MedoSigner import Argus, Gorgon, md5, Ladon

#+------------------------------------------------------+
#| Author : L7N                                       |
#| Telegram : t.me/PyL7N                     |
#| Github : https://github.com/is-L7N  |
#+------------------------------------------------------+

class TikTok:
    def __init__(self, sessionid: str, proxy: str = None) -> None:
        self.sessionid = sessionid
        self.base_url = "https://api22-normal-c-alisg.tiktokv.com"
        self.headers = {
            'User-Agent': "com.zhiliaoapp.musically.gp/380602 (Linux; U; Android 12; ar_IQ; SO-51A; Build/58.2.B.0.520;tt-ok/3.12.13.32-ul)",
            'Cookie': f"sessionid={sessionid}"
        }
        self.params = {
            'iid': str(random.randint(1, 10**19)),
            'openudid': str(binascii.hexlify(os.urandom(8)).decode()),
            'cdid': str(uuid.uuid4()),
            'device_id': str(random.randint(1, 10**19)),
            'region': "IQ",
            'aid': "1340",
        }
        # Set up proxy configuration for requests calls
        self.proxies = None
        if proxy:
            self.proxies = {
                'http': proxy,
                'https': proxy,
            }

    def _sign(self, params, payload: str = None, sec_device_id: str = "", aid: int = 567753,
              license_id: int = 1611921764, sdk_version_str: str = "2.3.1.i18n",
              sdk_version: int = 2, platform: int = 19, unix: int = None):

        x_ss_stub = md5(payload.encode('utf-8')).hexdigest() if payload else None
        if not unix:
            unix = int(time.time())
        return Gorgon(params, unix, payload, self.headers.get("Cookie")).get_value() | {
            "x-ladon": Ladon.encrypt(unix, license_id, aid),
            "x-argus": Argus.get_sign(
                params,
                x_ss_stub,
                unix,
                platform=platform,
                aid=aid,
                license_id=license_id,
                sec_device_id=sec_device_id,
                sdk_version=sdk_version_str,
                sdk_version_int=sdk_version,
            ),
        }

    def get_feed(self) -> list:
        """Fetch recommended videos from the For You feed for warm-up targets.

        Returns:
            A list of dicts with 'aweme_id' and 'author_uid' keys from the feed.
            Falls back to a list of aweme_id strings if author info is unavailable.
        """
        url = f"{self.base_url}/aweme/v1/feed/"
        params = self.params.copy()
        headers = self.headers.copy()
        params.update({
            'count': '10',
            'version_name': '38.6.2',
        })

        signature = self._sign(urlencode(params), payload="")
        headers.update({
            'x-argus': signature["x-argus"],
            'x-gorgon': signature["x-gorgon"],
            'x-khronos': signature["x-khronos"],
            'x-ladon': signature["x-ladon"],
        })

        try:
            response = requests.get(url, params=params, headers=headers, proxies=self.proxies)
            data = response.json()
            aweme_list = data.get("aweme_list", [])
            results = []
            for item in aweme_list:
                aweme_id = item.get("aweme_id")
                if not aweme_id:
                    continue
                author_uid = None
                author = item.get("author")
                if author and isinstance(author, dict):
                    author_uid = author.get("uid")
                results.append({"aweme_id": aweme_id, "author_uid": author_uid})
            return results
        except Exception:
            return []

    def watch_video(self, aweme_id: str) -> bool:
        """Simulate watching a video by calling the video detail endpoint with a delay.

        Args:
            aweme_id: The video ID to watch.

        Returns:
            True if the video was fetched successfully, False otherwise.
        """
        url = f"{self.base_url}/aweme/v1/aweme/detail/"
        params = self.params.copy()
        headers = self.headers.copy()
        params.update({
            'aweme_id': aweme_id,
            'version_name': '38.6.2',
        })

        signature = self._sign(urlencode(params), payload="")
        headers.update({
            'x-argus': signature["x-argus"],
            'x-gorgon': signature["x-gorgon"],
            'x-khronos': signature["x-khronos"],
            'x-ladon': signature["x-ladon"],
        })

        try:
            response = requests.get(url, params=params, headers=headers, proxies=self.proxies)
            # Simulate watch time (3-7 seconds)
            time.sleep(3 + random.randint(0, 4))
            return response.status_code == 200
        except Exception:
            return False

    def like_video(self, aweme_id: str) -> bool:
        """Like a video (digg endpoint).

        Args:
            aweme_id: The video ID to like.

        Returns:
            True if the like was successful, False otherwise.
        """
        url = f"{self.base_url}/aweme/v1/commit/item/digg/"
        params = self.params.copy()
        headers = self.headers.copy()
        params.update({
            'version_name': '38.6.2',
        })

        data = {
            'aweme_id': aweme_id,
            'type': '1',
        }

        signature = self._sign(urlencode(params), urlencode(data))
        headers.update({
            'x-argus': signature["x-argus"],
            'x-gorgon': signature["x-gorgon"],
            'x-khronos': signature["x-khronos"],
            'x-ladon': signature["x-ladon"],
        })

        try:
            response = requests.post(url, params=params, data=data, headers=headers, proxies=self.proxies)
            result = response.json()
            return result.get("status_code") == 0
        except Exception:
            return False

    def follow_user(self, user_id: str) -> bool:
        """Follow a user by user_id.

        Args:
            user_id: The user ID to follow.

        Returns:
            True if the follow was successful, False otherwise.
        """
        url = f"{self.base_url}/aweme/v1/commit/follow/user/"
        params = self.params.copy()
        headers = self.headers.copy()
        params.update({
            'version_name': '38.6.2',
        })

        data = {
            'user_id': user_id,
            'type': '1',
        }

        signature = self._sign(urlencode(params), urlencode(data))
        headers.update({
            'x-argus': signature["x-argus"],
            'x-gorgon': signature["x-gorgon"],
            'x-khronos': signature["x-khronos"],
            'x-ladon': signature["x-ladon"],
        })

        try:
            response = requests.post(url, params=params, data=data, headers=headers, proxies=self.proxies)
            result = response.json()
            return result.get("status_code") == 0
        except Exception:
            return False

    def get_video(self) -> list:
        url = f"{self.base_url}/tiktok/user/relation/maf/list/v1"
        params = self.params.copy()
        headers = self.headers.copy()
        params.update({
            'scene': "15",
            'count': "20",
            'version_name': "38.6.2"
        })

        signature = self._sign(urlencode(params), payload="")
        headers.update({
            'x-argus': signature["x-argus"],
            'x-gorgon': signature["x-gorgon"],
            'x-khronos': signature["x-khronos"],
            'x-ladon': signature["x-ladon"],
        })

        try:
            response = requests.get(url, params=params, headers=headers, proxies=self.proxies).text
            aweme_ids = re.findall(r'"aweme_id":"(\d+)"', response)
            return list(set(aweme_ids))
        except Exception:
            return []

    def send(self, comment: str, aweme_id: str) -> Union[bool, str]:
        url = f"{self.base_url}/lite/v2/comment/publication/"
        params = self.params.copy()
        headers = self.headers.copy()
        params.update({
            'version_name': "38.6.2",
        })

        data = {
            'aweme_id': int(aweme_id),
            'text': str(comment),
        }

        signature = self._sign(urlencode(params), urlencode(data))
        headers.update({
            'x-argus': signature["x-argus"],
            'x-gorgon': signature["x-gorgon"],
            'x-khronos': signature["x-khronos"],
            'x-ladon': signature["x-ladon"],
        })

        try:
            response = requests.post(url, params=params, data=data, headers=headers, proxies=self.proxies).json()
            if response.get("status_msg") == "Comment sent successfully":
                return True
            elif response.get("status_msg") == "You're commenting too fast. Take a break!":
                return "Spam"
            else:
                return False            
        except Exception:
            return False


if __name__ == "__main__":
    info = [
    "Author : L7N 🇮🇶",
    "Telegram : t.me/PyL7N",
    "Github : https://github.com/is-L7N"
]

    width = max(len(line) for line in info) + 4
    border = "+" + "-" * (width - 2) + "+"
    
    print(border)
    for line in info:
        print("| " + line.ljust(width - 4) + " |")
    print(border)
    
    sessionid = input("\nEnter your TikTok Sessionid : ")
    tiktok = TikTok(sessionid)

    if not os.path.exists("comments.json"):
        with open("comments.json", "w") as f:
            json.dump({"EN": [], "AR": []}, f, indent=4)

    with open("comments.json", "r") as f:
        com = json.load(f)

    lang = input("\nChoose comment language (EN ~ AR) : ").strip().upper()
    comments = com.get(lang, [])

    if not comments:
        try:
            num = int(input("\nYou Dont Save Comments File How Many Comments do You Want to Add? : "))
            for i in range(num):
                c = input(f"Comment {i+1}: ")
                comments.append(c)
            com[lang] = comments
            with open("comments.json", "w") as f:
                json.dump(com, f, indent=4)
        except ValueError:
            print("\nPut Number not shit! ")
            comments = ["محتاجة صديق 😊🍑"]
    print("\n")
    while True:
        videos = tiktok.get_video()
        if videos:
            for vid in videos:
                comment = random.choice(comments)
                result = tiktok.send(comment, vid)
                if result == "Spam":
                    print("Spam Comments ! ")
                    time.sleep(10)
                elif result:
                    print(f"Sent : {comment} to : {vid}")
                else:
                    print(f"Not Sent to : {vid}")
        else:
            time.sleep(1)
        time.sleep(2)
