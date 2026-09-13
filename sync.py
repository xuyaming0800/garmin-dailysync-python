#!/usr/bin/env python3

import argparse
import fcntl
import getpass
import io
import os
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from garminconnect import Garmin

BASE_DIR = Path("/opt/garmin-auth")

CN_TOKEN_DIR = BASE_DIR / "cn_tokens"
GLOBAL_TOKEN_DIR = BASE_DIR / "global_tokens"

DB_PATH = BASE_DIR / "sync_state.db"
LOCK_PATH = BASE_DIR / "sync.lock"

SYNC_LIMIT = int(os.getenv("GARMIN_SYNC_LIMIT", "20"))
SYNC_START_TIME = os.getenv("GARMIN_SYNC_START_TIME")
MAX_SYNC_PAGES = 500


def log(msg):
    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}",
        flush=True,
    )


def parse_sync_start_time(value):
    """解析用户指定的同步起始时间（按 Garmin 活动本地时间）。"""

    if value is None:
        return None

    value = value.strip()

    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "开始同步时间格式错误，请使用 YYYY-MM-DD、"
            "YYYY-MM-DD HH:MM[:SS] 或 YYYY-MM-DDTHH:MM[:SS]"
        ) from exc

    if parsed.tzinfo is not None:
        raise argparse.ArgumentTypeError(
            "开始同步时间请使用本地时间，不要附带时区"
        )

    return parsed


def get_activity_start_datetime(activity):
    """读取 Garmin 活动时间；优先使用与参数语义一致的本地时间。"""

    value = (
        activity.get("startTimeLocal")
        or activity.get("startTimeGMT")
    )

    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            str(value).strip().replace("Z", "+00:00")
        )
    except ValueError:
        return None

    # startTimeGMT 偶尔会带时区；此处只用于和 Garmin 本地时间边界比较。
    return parsed.replace(tzinfo=None)


def load_activities(cn, start_time=None):
    """读取待检查活动；指定起始时间后自动翻页到该时间边界。"""

    if start_time is None:
        log(f"读取中国区最近 {SYNC_LIMIT} 条活动")
        return cn.get_activities(0, SYNC_LIMIT) or []

    log(
        "读取中国区活动，开始同步时间（本地时间）: "
        f"{start_time.isoformat(sep=' ', timespec='seconds')}"
    )

    activities = []
    offset = 0

    for _ in range(MAX_SYNC_PAGES):
        page = cn.get_activities(offset, SYNC_LIMIT) or []

        if not page:
            break

        reached_start_time = False

        for activity in page:
            activity_time = get_activity_start_datetime(activity)

            if activity_time is None:
                log(
                    "跳过无法解析开始时间的活动: "
                    f"{activity.get('activityId')}"
                )
                continue

            if activity_time >= start_time:
                activities.append(activity)
            else:
                reached_start_time = True

        if reached_start_time or len(page) < SYNC_LIMIT:
            break

        offset += len(page)
    else:
        raise RuntimeError(
            f"读取活动达到安全上限 {MAX_SYNC_PAGES} 页，"
            "请设置更晚的开始同步时间"
        )

    return activities


def init_db():
    conn = sqlite3.connect(DB_PATH)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS synced_activity (
            cn_activity_id TEXT PRIMARY KEY,
            activity_name TEXT,
            start_time TEXT,
            synced_at TEXT,
            status TEXT
        )
        """
    )

    conn.commit()
    return conn


def already_synced(conn, activity_id):
    row = conn.execute(
        """
        SELECT 1
        FROM synced_activity
        WHERE cn_activity_id = ?
        """,
        (str(activity_id),),
    ).fetchone()

    return row is not None


def mark_synced(
    conn,
    activity_id,
    activity_name,
    start_time,
    status="ok",
):
    conn.execute(
        """
        INSERT OR REPLACE INTO synced_activity
        (
            cn_activity_id,
            activity_name,
            start_time,
            synced_at,
            status
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            str(activity_id),
            activity_name,
            start_time,
            datetime.now().isoformat(timespec="seconds"),
            status,
        ),
    )

    conn.commit()


def load_cn():
    token_file = CN_TOKEN_DIR / "garmin_tokens.json"

    if not token_file.exists():
        raise RuntimeError(
            f"找不到中国区 token: {token_file}\n"
            "请先完成中国区 MFA 登录。"
        )

    log("加载 Garmin 中国区 Token")

    client = Garmin(is_cn=True)
    client.login(str(CN_TOKEN_DIR))

    log(f"中国区登录成功: {client.get_full_name()}")

    return client


def load_global():
    token_file = GLOBAL_TOKEN_DIR / "garmin_tokens.json"

    if not token_file.exists():
        raise RuntimeError(
            "国际区尚未初始化。\n"
            "请先运行:\n"
            "python sync.py --init-global"
        )

    log("加载 Garmin 国际区 Token")

    client = Garmin(is_cn=False)
    client.login(str(GLOBAL_TOKEN_DIR))

    log(f"国际区登录成功: {client.get_full_name()}")

    return client


def init_global():
    GLOBAL_TOKEN_DIR.mkdir(
        parents=True,
        exist_ok=True,
        mode=0o700,
    )

    email = input("Garmin 国际区邮箱: ").strip()
    password = getpass.getpass("Garmin 国际区密码: ")

    def mfa():
        return input("Garmin 国际区验证码: ").strip()

    log("登录 Garmin 国际区")

    client = Garmin(
        email=email,
        password=password,
        is_cn=False,
        prompt_mfa=mfa,
    )

    client.login(str(GLOBAL_TOKEN_DIR))

    token_file = GLOBAL_TOKEN_DIR / "garmin_tokens.json"

    if token_file.exists():
        os.chmod(token_file, 0o600)

    os.chmod(GLOBAL_TOKEN_DIR, 0o700)

    log(f"国际区登录成功: {client.get_full_name()}")
    log(f"Token 已保存到 {GLOBAL_TOKEN_DIR}")
    log("以后不需要保存国际区密码。")


def extract_fit(data, activity_id, output_dir):
    """
    Garmin ORIGINAL 下载通常为 ZIP。
    找到其中的 .fit 文件并解压。
    """

    bio = io.BytesIO(data)

    # 有些情况下可能直接返回 FIT
    if not zipfile.is_zipfile(bio):
        fit_path = output_dir / f"{activity_id}.fit"
        fit_path.write_bytes(data)
        return fit_path

    bio.seek(0)

    with zipfile.ZipFile(bio) as zf:
        fit_files = [
            name
            for name in zf.namelist()
            if name.lower().endswith(".fit")
        ]

        if not fit_files:
            raise RuntimeError(
                f"Activity {activity_id} 的 ZIP 中没有 FIT 文件"
            )

        # 一般一个活动只有一个 FIT
        source_name = fit_files[0]

        fit_path = output_dir / f"{activity_id}.fit"

        with zf.open(source_name) as src:
            fit_path.write_bytes(src.read())

        return fit_path


def sync_one(
    cn,
    global_client,
    conn,
    activity,
    dry_run=False,
):
    activity_id = str(activity.get("activityId"))

    name = (
        activity.get("activityName")
        or activity.get("activityType", {}).get("typeKey")
        or "Unknown"
    )

    start_time = (
        activity.get("startTimeLocal")
        or activity.get("startTimeGMT")
        or ""
    )

    if not activity_id or activity_id == "None":
        log("跳过没有 activityId 的活动")
        return

    if already_synced(conn, activity_id):
        log(f"跳过已同步: {activity_id} {name}")
        return

    log(
        f"发现新活动: "
        f"{activity_id} | {start_time} | {name}"
    )

    if dry_run:
        log("DRY-RUN: 不下载、不上传")
        return

    with tempfile.TemporaryDirectory(
        prefix="garmin-sync-"
    ) as tmp:
        tmpdir = Path(tmp)

        log(f"下载 FIT: {activity_id}")

        raw = cn.download_activity(
            activity_id,
            dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL,
        )

        fit_path = extract_fit(
            raw,
            activity_id,
            tmpdir,
        )

        size_kb = fit_path.stat().st_size / 1024

        log(
            f"FIT 下载完成: "
            f"{fit_path.name} ({size_kb:.1f} KB)"
        )

        try:
            log("上传到 Garmin 国际区")

            result = global_client.upload_activity(
                str(fit_path)
            )

            log(f"上传成功: {activity_id}")

            mark_synced(
                conn,
                activity_id,
                name,
                start_time,
                "ok",
            )

            return result

        except Exception as exc:
            text = str(exc)

            # Garmin 已存在同一个 FIT 时通常返回 409
            if "409" in text or "Conflict" in text:
                log(
                    f"国际区已有该活动，标记为完成: "
                    f"{activity_id}"
                )

                mark_synced(
                    conn,
                    activity_id,
                    name,
                    start_time,
                    "duplicate",
                )
                return

            raise


def run_sync(dry_run=False, start_time=None):
    BASE_DIR.mkdir(
        parents=True,
        exist_ok=True,
        mode=0o700,
    )

    # 防止 cron 重叠执行
    lock_fp = open(LOCK_PATH, "w")

    try:
        fcntl.flock(
            lock_fp,
            fcntl.LOCK_EX | fcntl.LOCK_NB,
        )
    except BlockingIOError:
        log("已有同步任务正在运行，本次退出。")
        return

    conn = init_db()

    try:
        cn = load_cn()
        global_client = load_global()

        activities = load_activities(
            cn,
            start_time=start_time,
        )

        log(f"获取到 {len(activities)} 条活动")

        #
        # Garmin 默认 newest -> oldest
        # 反转后 oldest -> newest 上传
        #
        activities.reverse()

        success = 0
        failed = 0

        for activity in activities:
            try:
                before = already_synced(
                    conn,
                    activity.get("activityId"),
                )

                sync_one(
                    cn,
                    global_client,
                    conn,
                    activity,
                    dry_run=dry_run,
                )

                after = already_synced(
                    conn,
                    activity.get("activityId"),
                )

                if not before and after:
                    success += 1

            except Exception as exc:
                failed += 1

                log(
                    f"同步失败 activityId="
                    f"{activity.get('activityId')}: {exc}"
                )

        log(
            f"同步结束: "
            f"新增完成={success}, "
            f"失败={failed}"
        )

        if failed:
            sys.exit(2)

    finally:
        conn.close()
        fcntl.flock(lock_fp, fcntl.LOCK_UN)
        lock_fp.close()


def show_state():
    conn = init_db()

    rows = conn.execute(
        """
        SELECT
            cn_activity_id,
            start_time,
            activity_name,
            synced_at,
            status
        FROM synced_activity
        ORDER BY synced_at DESC
        LIMIT 30
        """
    ).fetchall()

    conn.close()

    if not rows:
        print("暂无同步记录")
        return

    for row in rows:
        print(
            f"{row[0]} | "
            f"{row[1]} | "
            f"{row[2]} | "
            f"{row[4]} | "
            f"{row[3]}"
        )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Garmin 中国区 -> 国际区活动同步"
        )
    )

    parser.add_argument(
        "--init-global",
        action="store_true",
        help="首次初始化 Garmin 国际区登录",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只检查活动，不上传",
    )

    parser.add_argument(
        "--start-time",
        type=parse_sync_start_time,
        default=SYNC_START_TIME,
        metavar="TIME",
        help=(
            "只同步此本地时间（含）之后的活动；支持 YYYY-MM-DD "
            "或 YYYY-MM-DD HH:MM[:SS]；也可设置环境变量 "
            "GARMIN_SYNC_START_TIME"
        ),
    )

    parser.add_argument(
        "--state",
        action="store_true",
        help="查看最近同步记录",
    )

    args = parser.parse_args()

    if args.init_global:
        init_global()
        return

    if args.state:
        show_state()
        return

    run_sync(
        dry_run=args.dry_run,
        start_time=args.start_time,
    )


if __name__ == "__main__":
    main()
