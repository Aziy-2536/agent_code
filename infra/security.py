"""密钥、脱敏和安全辅助功能。

PII（个人敏感信息）处理原则（从建模层定死，不是后期补丁）：
1. 身份证号（高敏）三层存储：
   - hash：SHA-256 摘要，用于等值匹配/去重（不可逆，类比密码存储）
   - enc ：AES-GCM 密文，用于低频明文核验（可逆，密钥在应用层）
   - masked：脱敏副本（440106********1234），展示零解密成本
2. 姓名/电话（中敏）：明文存储 + 出库前脱敏（mask_* 函数）——展示是常态，核验非常态
3. 脱敏必须在"数据出库前"完成（Repository 层），前端/接口永远拿不到明文
4. AES-GCM 是认证加密（密文+tag），比 ECB/CBC 安全：能检测篡改
"""
import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from config.settings import get_settings


# ==================== PII 加密（AES-GCM） ====================

def _pii_key() -> bytes:
    """从配置取 PII 密钥，派生为 32 字节 AES-256 密钥。

    密钥派生：SHA-256(secret) —— 把任意长度的配置串变成固定 32 字节。
    生产环境应改用 KMS/HSM 管理，此处为应用层密钥（.env 的 PII_SECRET_KEY）。
    """
    secret = get_settings().pii_secret_key.encode("utf-8")
    return hashlib.sha256(secret).digest()


def encrypt_pii(plaintext: str) -> str:
    """AES-GCM 加密：返回 base64(iv + ciphertext + tag) 字符串。

    - 每次加密生成随机 12 字节 IV（同一明文每次密文不同，防模式分析）
    - 输出为 URL-safe base64，可直接存 VARCHAR/JSON
    """
    if not plaintext:
        return ""
    key = _pii_key()
    iv = os.urandom(12)  # GCM 标准 IV 长度 12 字节
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
    # 打包：iv + 密文 + tag 拼一起 base64，解密时按长度切回
    payload = iv + ciphertext
    return base64.urlsafe_b64encode(payload).decode("ascii")


def decrypt_pii(token: str) -> str:
    """AES-GCM 解密：encrypt_pii 的逆操作。

    密文被篡改/密钥不对 → 抛 InvalidTag 异常（GCM 的完整性校验）。
    """
    if not token:
        return ""
    key = _pii_key()
    payload = base64.urlsafe_b64decode(token.encode("ascii"))
    iv = payload[:12]
    ciphertext = payload[12:]
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(iv, ciphertext, None)
    return plaintext.decode("utf-8")


def hash_pii(plaintext: str) -> str:
    """SHA-256 摘要（不可逆）：身份证等值匹配/去重用。

    为什么用 SHA-256 而不用 bcrypt：
    - 身份证是 18 位固定格式、高熵（生日+序号+校验位），暴力破解空间远小于密码
    - 需要确定性：同一身份证两次 hash 结果必须一致（匹配用）
    - bcrypt 加盐后不可复现，无法用于等值查询；SHA-256 确定但无盐——
      身份证自身熵高，彩虹表不现实，可接受
    """
    if not plaintext:
        return ""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


# ==================== 脱敏（出库前调用） ====================

def mask_name(name: str) -> str:
    """姓名脱敏：保留首尾，中间打星。
    王小明 → 王*明；王小明三字 → 王*明；两字 王明 → 王*；单字 → *
    """
    if not name:
        return ""
    if len(name) == 1:
        return "*"
    if len(name) == 2:
        return name[0] + "*"
    return name[0] + "*" * (len(name) - 2) + name[-1]


def mask_phone(phone: str) -> str:
    """手机号脱敏：保留前 3 后 4。13800138000 → 138****8000"""
    if not phone:
        return ""
    if len(phone) < 7:
        return "*" * len(phone)
    return phone[:3] + "****" + phone[-4:]


def mask_id_card(id_card: str) -> str:
    """身份证脱敏：保留前 6 后 4。440106199001011234 → 440106********1234"""
    if not id_card:
        return ""
    if len(id_card) < 10:
        return "*" * len(id_card)
    return id_card[:6] + "*" * (len(id_card) - 10) + id_card[-4:]


def mask_address(addr: str) -> str:
    """用电地址脱敏：保留到"路/街/小区"级，隐去门牌号+栋+房号。

    地址最敏感的部分是"精确到门牌号"（=物理定位），必须隐去。
    广东省东莞市虎门镇太沙路128号幸福小区3栋501
      → 广东省东莞市虎门镇太沙路********
    广东省东莞市虎门镇太沙路128号
      → 广东省东莞市虎门镇太沙路********

    实现：截断到第一个数字（门牌号起点）之前，后续打星。
    """
    if not addr:
        return ""
    # 找第一个数字的位置（门牌号/栋号起点）
    import re

    m = re.search(r"\d", addr)
    if m is None:
        return addr  # 没有门牌号（如只到镇街级），视为已足够模糊
    return addr[: m.start()] + "*" * 8


def mask_pii_row(row: dict, *, include_id_card: bool = False) -> dict:
    """整行脱敏（Repository 出库统一入口）：按字段名应用对应脱敏函数。

    - row: 含 customer_name / phone / id_card 等明文的 dict
    - include_id_card=True 时才脱敏身份证（默认不输出该字段，除非业务需要）
    """
    masked = dict(row)
    if "customer_name" in masked and masked["customer_name"]:
        masked["customer_name"] = mask_name(str(masked["customer_name"]))
    if "phone" in masked and masked["phone"]:
        masked["phone"] = mask_phone(str(masked["phone"]))
    if "address" in masked and masked["address"]:
        masked["address"] = mask_address(str(masked["address"]))
    if include_id_card and "id_card" in masked and masked["id_card"]:
        masked["id_card"] = mask_id_card(str(masked["id_card"]))
    return masked


# ==================== 通用安全辅助 ====================

def generate_secret_key(length: int = 32) -> str:
    """生成随机密钥（.env 的 PII_SECRET_KEY / JWT_SECRET 初始化用）。"""
    return base64.urlsafe_b64encode(os.urandom(length)).decode("ascii")
