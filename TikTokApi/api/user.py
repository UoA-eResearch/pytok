from __future__ import annotations

import json
import re
import time
from urllib.parse import quote, urlencode

import requests
import seleniumwire
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException

from ..exceptions import *
from ..helpers import extract_tag_contents

from typing import TYPE_CHECKING, ClassVar, Iterator, Optional

if TYPE_CHECKING:
    from ..tiktok import TikTokApi
    from .video import Video

from .base import Base


class User(Base):
    """
    A TikTok User.

    Example Usage
    ```py
    user = api.user(username='therock')
    # or
    user_id = '5831967'
    sec_uid = 'MS4wLjABAAAA-VASjiXTh7wDDyXvjk10VFhMWUAoxr8bgfO1kAL1-9s'
    user = api.user(user_id=user_id, sec_uid=sec_uid)
    ```

    """

    parent: ClassVar[TikTokApi]

    user_id: str
    """The user ID of the user."""
    sec_uid: str
    """The sec UID of the user."""
    username: str
    """The username of the user."""
    as_dict: dict
    """The raw data associated with this user."""

    def __init__(
        self,
        username: Optional[str] = None,
        user_id: Optional[str] = None,
        sec_uid: Optional[str] = None,
        data: Optional[dict] = None,
    ):
        """
        You must provide the username or (user_id and sec_uid) otherwise this
        will not function correctly.
        """
        self.__update_id_sec_uid_username(user_id, sec_uid, username)
        if data is not None:
            self.as_dict = data
            self.__extract_from_data()

    def info(self, **kwargs):
        """
        Returns a dictionary of TikTok's User object

        Example Usage
        ```py
        user_data = api.user(username='therock').info()
        ```
        """
        return self.info_full(**kwargs)["user"]

    def info_full(self, **kwargs) -> dict:
        """
        Returns a dictionary of information associated with this User.
        Includes statistics about this user.

        Example Usage
        ```py
        user_data = api.user(username='therock').info_full()
        ```
        """

        # TODO: Find the one using only user_id & sec_uid
        if not self.username:
            raise TypeError(
                "You must provide the username when creating this class to use this method."
            )

        quoted_username = quote(self.username)
        r = requests.get(
            "https://tiktok.com/@{}?lang=en".format(quoted_username),
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
                "path": "/@{}".format(quoted_username),
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
                "User-Agent": self.parent._user_agent,
            },
            proxies=User.parent._format_proxy(kwargs.get("proxy", None)),
            cookies=User.parent._get_cookies(**kwargs),
            **User.parent._requests_extra_kwargs,
        )

        data = extract_tag_contents(r.text)
        user = json.loads(data)

        user_props = user["props"]["pageProps"]
        if user_props["statusCode"] == 404:
            raise NotFoundException(
                "TikTok user with username {} does not exist".format(self.username)
            )

        return user_props["userInfo"]

    def videos(self, count=30, cursor=0, **kwargs) -> Iterator[Video]:
        """
        Returns an iterator yielding Video objects.

        - Parameters:
            - count (int): The amount of videos you want returned.
            - cursor (int): The unix epoch to get uploaded videos since.

        Example Usage
        ```py
        user = api.user(username='therock')
        for video in user.videos(count=100):
            # do something
        ```
        """

        driver = User.parent._browser

        driver.get(f"https://www.tiktok.com/@{self.username}")

        self.wait_for_content_or_captcha('user-post-item')

        request_num = 1
        amount_yielded = 0
        searched_urls = []

        while amount_yielded < count:

            if request_num == 1:
                path = f"@{self.username}"
            elif request_num > 1:
                path = "api/post/item_list"

            search_requests = self.get_requests(path)
            for request in search_requests:
                searched_urls.append(request.url)
                body = self.get_response_body(request)

                if request_num == 1:
                    tag_contents = extract_tag_contents(body)
                    res = json.loads(tag_contents)

                    videos = [val for key, val in res['ItemModule'].items()]
                    for video in videos:
                        video['createTime'] = int(video['createTime'])
                        author_name = video['author']
                        video['author'] = {
                            "id": video["authorId"],
                            "uniqueId": author_name,
                            "nickname": video["nickname"],
                            "avatarThumb": video["avatarThumb"],
                            "signature": res["UserModule"]["users"][author_name]["signature"],
                            "verified": res["UserModule"]["users"][author_name]["verified"],
                            "secUid": video["authorSecId"],
                            "secret": res["UserModule"]["users"][author_name]["secret"],
                            "ftc": res["UserModule"]["users"][author_name]["ftc"],
                            "relation": res["UserModule"]["users"][author_name]["relation"],
                            "openFavorite": res["UserModule"]["users"][author_name]["openFavorite"],
                            "commentSetting": res["UserModule"]["users"][author_name]["commentSetting"],
                            "duetSetting": res["UserModule"]["users"][author_name]["duetSetting"],
                            "stitchSetting": res["UserModule"]["users"][author_name]["stitchSetting"],
                            "privateAccount": res["UserModule"]["users"][author_name]["privateAccount"]
                        }

                elif request_num > 1:
                    res = json.loads(body)
                    if res.get('type') == 'verify':
                        # this is the captcha denied response
                        continue

                    videos = res.get("itemList", [])

                amount_yielded += len(videos)
                for video in videos:
                    yield self.parent.video(data=video)

                if request_num == 1:
                    has_more = res['ItemList']['user-post']['hasMore']
                else:
                    has_more = res.get("hasMore", False)

                if not has_more:
                    User.parent.logger.info(
                        "TikTok isn't sending more TikToks beyond this point."
                    )
                    return

            # Scroll down to bottom
            self.scroll_to_bottom()
            self.wait_until_not_skeleton_or_captcha('video-skeleton-container')

            request_num += 1

            self.parent.request_delay()


    def liked(self, count: int = 30, cursor: int = 0, **kwargs) -> Iterator[Video]:
        """
        Returns a dictionary listing TikToks that a given a user has liked.

        **Note**: The user's likes must be **public** (which is not the default option)

        - Parameters:
            - count (int): The amount of videos you want returned.
            - cursor (int): The unix epoch to get uploaded videos since.

        Example Usage
        ```py
        for liked_video in api.user(username='public_likes'):
            # do something
        ```
        """
        processed = User.parent._process_kwargs(kwargs)
        kwargs["custom_device_id"] = processed.device_id

        amount_yielded = 0
        first = True

        if self.user_id is None and self.sec_uid is None:
            self.__find_attributes()

        while amount_yielded < count:
            query = {
                "count": 30,
                "id": self.user_id,
                "type": 2,
                "secUid": self.sec_uid,
                "cursor": cursor,
                "sourceType": 9,
                "appId": 1233,
                "region": processed.region,
                "priority_region": processed.region,
                "language": processed.language,
            }
            path = "api/favorite/item_list/?{}&{}".format(
                User.parent._add_url_params(), urlencode(query)
            )

            res = self.parent.get_data(path, **kwargs)

            if "itemList" not in res.keys():
                if first:
                    User.parent.logger.error("User's likes are most likely private")
                return

            videos = res.get("itemList", [])
            amount_yielded += len(videos)
            for video in videos:
                amount_yielded += 1
                yield self.parent.video(data=video)

            if not res.get("hasMore", False) and not first:
                User.parent.logger.info(
                    "TikTok isn't sending more TikToks beyond this point."
                )
                return

            cursor = res["cursor"]
            first = False

    def __extract_from_data(self):
        data = self.as_dict
        keys = data.keys()

        if "user_info" in keys:
            self.__update_id_sec_uid_username(
                data["user_info"]["uid"],
                data["user_info"]["sec_uid"],
                data["user_info"]["unique_id"],
            )
        elif "uniqueId" in keys:
            self.__update_id_sec_uid_username(
                data["id"], data["secUid"], data["uniqueId"]
            )

        if None in (self.username, self.user_id, self.sec_uid):
            User.parent.logger.error(
                f"Failed to create User with data: {data}\nwhich has keys {data.keys()}"
            )

    def __update_id_sec_uid_username(self, id, sec_uid, username):
        self.user_id = id
        self.sec_uid = sec_uid
        self.username = username

    def __find_attributes(self) -> None:
        # It is more efficient to check search first, since self.user_object() makes HTML request.
        found = False
        for u in self.parent.search.users(self.username):
            if u.username == self.username:
                found = True
                self.__update_id_sec_uid_username(u.user_id, u.sec_uid, u.username)
                break

        if not found:
            user_object = self.info()
            self.__update_id_sec_uid_username(
                user_object["id"], user_object["secUid"], user_object["uniqueId"]
            )

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return f"TikTokApi.user(username='{self.username}', user_id='{self.user_id}', sec_uid='{self.sec_uid}')"

    def __getattr__(self, name):
        if name in ["as_dict"]:
            self.as_dict = self.info()
            self.__extract_from_data()
            return self.__getattribute__(name)

        raise AttributeError(f"{name} doesn't exist on TikTokApi.api.User")
