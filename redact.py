"""返回结果的凭据脱敏。

**默认开启**，显式 ``--no-redact`` 才关闭。

为什么必须按字段名做**无条件**遮蔽，而不是按"这个监控属于什么类型"推断：

* 实测 ``get_monitors`` 里 **30/69** 个监控把数据库密码内嵌在 ``databaseConnectionString``
  （形如 ``scheme://user:password@host``）。
* 实测 ``radiusPassword`` 在 **28/69** 个监控上非空，且与同一监控连接串里的密码**逐字节相同**
  —— 也就是说这个字段名会骗人：它并非只有 RADIUS 监控才有值。
* 实测 ``mqttUsername`` 在某个监控上装的是一整条**含密码的 URI**。

因此：**名单按字段名匹配，命中即遮蔽，绝不以"该字段对本类型监控应为空"为前提。**
任何"这个字段不该有值所以不用遮"的推理，在上述实测数据面前都是错的。
"""

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "***"


def _normalize(name: str) -> str:
    """统一字段名比较形式：小写并去掉分隔符。

    这样 ``basic_auth_pass``、``basic-auth-pass``、``basicAuthPass`` 都可命中同一条目。
    """
    return name.lower().replace("-", "").replace("_", "")


# 需要遮蔽的字段名（构造时统一规范化为无分隔符小写）。
# 按**字段名**匹配，与监控/通知类型无关。
SENSITIVE_FIELD_NAMES: frozenset[str] = frozenset(
    _normalize(name) for name in (
        # 通知：SMTP
        "smtpPassword", "smtpUsername", "smtpHost", "smtpFrom", "smtpTo", "smtpCC", "smtpBCC",
        # 通知：Webhook / 机器人（URL 内含 access_token）
        "webhookURL", "webhookAdditionalHeaders", "webhookCustomBody",
        "alertNowWebhookURL", "discordWebhookUrl", "feishuWebHookUrl",
        "googleChatWebhookURL", "slackwebhookURL", "squadcastWebhookURL",
        "stackfieldwebhookURL", "rocketwebhookURL", "mattermostWebhookUrl",
        "pagerdutyIntegrationUrl", "pagertreeIntegrationUrl", "barkEndpoint",
        "gotifyserverurl", "splunkRestURL", "ntfyserverurl", "signalURL",
        # 通知：各类 token / key / secret
        "telegramBotToken", "telegramChatID", "gotifyapplicationToken",
        "pushbulletAccessToken", "pushoveruserkey", "pushoverapptoken", "pushyAPIKey",
        "pushyToken", "pushdeerKey", "serverChanSendKey", "lunaseaUserID", "lunaseaDevice",
        "octopushAPIKey", "octopushLogin", "octopushPhoneNumber", "opsgenieApiKey",
        "pagerdutyIntegrationKey", "promosmsLogin", "promosmsPhoneNumber",
        "signalNumber", "signalRecipients", "smscLogin", "smscToNumber",
        "smseagleToken", "smseagleRecipient", "smsmanagerApiKey", "numbers",
        "twilioApiKey", "twilioAuthToken", "twilioToNumber", "twilioFromNumber",
        "weComBotKey", "barkGroup", "appriseURL", "longLivedAccessToken",
        "kookBotToken", "lineChannelAccessToken", "lineNotifyAccessToken",
        "internalRoomId", "accessToken", "accessKeyId", "secretAccessKey",
        "secretKey", "goAlertToken", "octopushSMSType",
        # 监控：连接串与凭据
        "databaseConnectionString", "radiusPassword", "radiusSecret", "radiusUsername",
        "mqttPassword", "mqttUsername", "pushToken", "basic_auth_pass", "basic_auth_user",
        "oauth_client_secret", "oauth_client_id", "tlsKey", "tlsCert", "tlsCa",
        "authDomain", "authWorkstation", "grpcMetadata", "grpcBody", "headers", "body",
        # 通用
        "password", "token", "apiKey", "key", "secret", "privateKey", "credential",
    )
)

# 这些字段名虽然敏感，但"空值/未配置"本身是有用信息，不应被遮成 ``***``。
_PRESERVE_EMPTY = (None, "", [], {})


_SENSITIVE_SUFFIXES = ("password", "passwd", "token", "apikey", "secret", "credential")
_SECRET_QUERY_NAMES = frozenset({
    "key", "apikey", "accesskey", "accesskeyid", "token", "accesstoken",
    "authtoken", "password", "passwd", "secret", "clientsecret", "signature",
    "authorization", "auth",
})
_URL_RE = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s\"'<>]+", re.IGNORECASE)


def _redact_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    try:
        parts = urlsplit(raw)
        if not parts.netloc:
            return raw
        netloc = parts.netloc
        changed = False
        if "@" in netloc:
            netloc = REDACTED + "@" + netloc.rsplit("@", 1)[1]
            changed = True
        query = parse_qsl(parts.query, keep_blank_values=True)
        if query:
            safe_query = []
            for key, value in query:
                secret = _normalize(key) in _SECRET_QUERY_NAMES and bool(value)
                safe_query.append((key, REDACTED if secret else value))
                changed = changed or secret
            query = safe_query
        fragment = parts.fragment
        if "=" in fragment:
            safe_fragment = []
            for key, value in parse_qsl(fragment, keep_blank_values=True):
                secret = _normalize(key) in _SECRET_QUERY_NAMES and bool(value)
                safe_fragment.append((key, REDACTED if secret else value))
                changed = changed or secret
            if changed and safe_fragment:
                fragment = urlencode(safe_fragment, safe="*")
        if not changed:
            return raw
        return urlunsplit((parts.scheme, netloc, parts.path,
                           urlencode(query, safe="*") if parts.query else "", fragment))
    except ValueError:
        return raw


def _redact_text(value: str) -> str:
    """遮蔽普通 URL 字段或错误文本中的 userinfo 与常见密钥查询参数。"""
    return _URL_RE.sub(_redact_url, value)


def _is_sensitive(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    name = _normalize(key)
    if name in SENSITIVE_FIELD_NAMES:
        return True
    if name.endswith(_SENSITIVE_SUFFIXES):
        return True
    # 带序号/后缀的变体，如 smtpPassword2 / smtpPassword_copy
    stripped = name.rstrip("0123456789")
    if stripped != name and (stripped in SENSITIVE_FIELD_NAMES
                             or stripped.endswith(_SENSITIVE_SUFFIXES)):
        return True
    return False



def redact(obj: Any) -> Any:
    """递归遮蔽敏感字段值。

    保留"原本是否为空"这一信息：``None``/空串/空容器照原样返回，
    非空值替换为 ``***``。这样调用方能区分"没配置"与"配置了但被遮"。
    """
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if _is_sensitive(key) and value not in _PRESERVE_EMPTY:
                out[key] = REDACTED
            else:
                out[key] = redact(value)
        return out
    if isinstance(obj, (list, tuple, set)):
        return [redact(item) for item in obj]
    if isinstance(obj, str):
        return _redact_text(obj)
    return obj


def redacted_fields(obj: Any, prefix: str = "") -> list[str]:
    """返回被遮蔽的字段路径列表，供调用方提示"哪些字段被遮了"。"""
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if _is_sensitive(key) and value not in _PRESERVE_EMPTY:
                found.append(path)
            else:
                found.extend(redacted_fields(value, path))
    elif isinstance(obj, (list, tuple, set)):
        for index, item in enumerate(obj):
            found.extend(redacted_fields(item, f"{prefix}[{index}]"))
    elif isinstance(obj, str) and _redact_text(obj) != obj:
        found.append(prefix)
    return found
