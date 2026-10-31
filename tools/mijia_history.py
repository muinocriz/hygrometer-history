#!/usr/bin/env python3
"""
导出米家蓝牙温湿度计2（LYWSD03MMC，原厂固件）中存储的每小时最高/最低温湿度到 CSV。

依赖：  pip install bleak
支持：  macOS、Windows 10/11、Linux（含树莓派）

用法：
  python mijia_history.py scan                         # 扫描设备
  python mijia_history.py <地址> -o history.csv        # 导出全部历史
  python mijia_history.py <地址> --last 48             # 只导出最近 48 小时
  python mijia_history.py auto                         # 自动连接第一个 LYWSD03MMC

  <地址>：macOS 上填 scan 显示的 UUID；Windows / Linux 上填 MAC 地址。

特性：
  - 传输卡住或断线时自动重连，从断点续传
  - 随时 Ctrl+C，已收到的数据照样写入 CSV
注意：
  - 运行前关闭手机米家 App（或关手机蓝牙），设备同一时间只允许一个连接
  - 不要拔电池，拔掉后设备里的历史数据会丢失
"""
import argparse
import asyncio
import csv
import struct
import time
from datetime import datetime

from bleak import BleakClient, BleakScanner

# ---------------- 时间参数（秒） ----------------
SCAN_SECONDS = 20       # scan 命令的扫描时长
FIND_SECONDS = 30       # 连接前查找设备，每次的扫描时长
FIND_TRIES = 3          # 查找设备的次数
CONNECT_TIMEOUT = 60    # 建立连接的超时
IDLE_SECONDS = 40       # 多久收不到新数据算卡住
RETRY_DELAY = 4         # 续传前的等待
RETRIES = 10            # 最多续传次数

# ---------------- 协议 ----------------
BASE = "-7a0a-4b0c-8a1a-6ff2997da3a6"
UUID_TIME = "ebe0ccb7" + BASE         # 设备时钟（未校时则为开机后秒数）
UUID_NUM_RECORDS = "ebe0ccb9" + BASE  # <II：总记录数, 当前存储记录数
UUID_RECORD_IDX = "ebe0ccba" + BASE   # <I：从第几条开始读
UUID_HISTORY = "ebe0ccbc" + BASE      # 通知：逐条推送历史记录

HISTORY_FMT = "<IIhBhB"  # 序号, 时间戳, 最高温×10, 最高湿, 最低温×10, 最低湿
HISTORY_LEN = struct.calcsize(HISTORY_FMT)

# 多次连接之间共享的结果（续传、Ctrl+C 时都能保存）
records: dict[int, tuple] = {}
clock_offset: float | None = None


# ---------------- 设备查找 ----------------
async def scan():
    print(f"扫描 {SCAN_SECONDS} 秒……")
    devices = await BleakScanner.discover(timeout=SCAN_SECONDS)
    hits = [d for d in devices if any(k in (d.name or "") for k in ("LYWSD03", "ATC", "MJ_HT"))]
    for d in hits:
        print(f"  {d.address}   {d.name}")
    if not hits:
        print("没有找到米家温湿度计。请确认设备在附近，并关闭手机米家 App 后重试。")


async def find_device(address: str):
    """先扫描再连接：macOS 上必须在同一进程里扫到设备才能连接。"""
    want = address.upper()

    def match(d, _adv):
        if want == "AUTO":
            return (d.name or "").startswith("LYWSD03")
        return d.address.upper() == want

    for i in range(1, FIND_TRIES + 1):
        print(f"查找设备（第 {i}/{FIND_TRIES} 次，最多 {FIND_SECONDS} 秒）……")
        d = await BleakScanner.find_device_by_filter(match, timeout=FIND_SECONDS)
        if d:
            return d
    return None


# ---------------- 一次连接内的接收 ----------------
async def session(device, start: int | None, last: int | None, first: bool) -> str:
    """连接一次并接收历史，返回 done / disconnected / stalled。"""
    global clock_offset
    disconnected = asyncio.Event()
    last_rx = time.monotonic()

    def on_history(_, data: bytearray):
        nonlocal last_rx
        last_rx = time.monotonic()
        if len(data) >= HISTORY_LEN:
            idx, ts, tmax, hmax, tmin, hmin = struct.unpack_from(HISTORY_FMT, data)
            records[idx] = (ts, tmin / 10, hmin, tmax / 10, hmax)

    async with BleakClient(device, timeout=CONNECT_TIMEOUT,
                           disconnected_callback=lambda _: disconnected.set()) as client:
        if clock_offset is None:
            raw = await client.read_gatt_char(UUID_TIME)
            clock_offset = time.time() - struct.unpack_from("<I", raw)[0]

        total, current = struct.unpack_from("<II", await client.read_gatt_char(UUID_NUM_RECORDS))
        expected = min(last, current) if last else current
        if first:
            print(f"设备共记录过 {total} 条，当前保存 {current} 条，本次读取 {expected} 条")

        if start is None and last:
            start = max(total - last + 1, 0)
        if start is not None:
            await client.write_gatt_char(UUID_RECORD_IDX, struct.pack("<I", start), response=True)

        await client.start_notify(UUID_HISTORY, on_history)
        last_rx = time.monotonic()
        while True:
            n = len(records)
            if n >= expected:
                return "done"
            if disconnected.is_set():
                return "disconnected"
            wait = time.monotonic() - last_rx
            if wait > IDLE_SECONDS:
                # 只差最后 1 条（当前小时还没写完）时视为完成
                return "done" if n >= expected - 1 else "stalled"
            tip = f"，已 {wait:.0f} 秒没有新数据" if wait > 5 else ""
            print(f"\r已接收 {n}/{expected} 条{tip}        ", end="", flush=True)
            await asyncio.sleep(0.5)


# ---------------- 主流程：连接 + 续传 ----------------
async def fetch(address: str, last: int | None):
    start = None
    no_progress = 0

    for attempt in range(RETRIES + 1):
        device = await find_device(address)
        if device is None:
            print("扫描不到设备。请确认：1) 手机米家 App 已关闭；2) 电脑离传感器足够近；"
                  "3) 地址与 scan 输出一致；4) 可尝试关闭再打开电脑蓝牙。")
            return
        if attempt == 0:
            print(f"连接 {device.address} ({device.name}) ……")

        before = len(records)
        try:
            status = await session(device, start, last, first=(attempt == 0))
        except Exception as e:
            status = f"连接出错（{type(e).__name__}: {e}）"
        print()

        if status == "done":
            return
        no_progress = no_progress + 1 if len(records) == before else 0
        if no_progress >= 3:
            print("连续 3 次都没有收到新数据，停止。")
            return
        if attempt == RETRIES:
            print(f"已续传 {RETRIES} 次，停止。")
            return

        if records:  # 从已收到的最大序号往前一条开始（重复的会自动去重）
            start = max(max(records) - 1, 0)
        reason = {"disconnected": "连接断开", "stalled": "传输停住"}.get(status, status)
        print(f"{reason}。{RETRY_DELAY} 秒后第 {attempt + 1}/{RETRIES} 次重试，"
              f"从第 {start or 0} 条开始 ……")
        await asyncio.sleep(RETRY_DELAY)


# ---------------- 输出 ----------------
def save_csv(out: str):
    if not records or clock_offset is None:
        print("没有收到任何历史记录。")
        return
    rows = []
    for idx in sorted(records):
        ts, tmin, hmin, tmax, hmax = records[idx]
        t = datetime.fromtimestamp(ts + clock_offset).replace(second=0, microsecond=0)
        rows.append((t.strftime("%Y-%m-%d %H:%M"), tmin, hmin, tmax, hmax))
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["时间(小时结束)", "最低温度℃", "最低湿度%", "最高温度℃", "最高湿度%"])
        w.writerows(rows)
    print(f"已导出 {len(rows)} 条到 {out}（{rows[0][0]} ~ {rows[-1][0]}）")


def main():
    global IDLE_SECONDS, RETRIES
    p = argparse.ArgumentParser(description="导出 LYWSD03MMC 每小时最高/最低温湿度")
    p.add_argument("address", help="设备地址；scan = 扫描；auto = 自动连接第一个 LYWSD03MMC")
    p.add_argument("-o", "--output", default="history.csv", help="输出 CSV 文件名")
    p.add_argument("--last", type=int, help="只读取最近 N 小时")
    p.add_argument("--idle", type=float, default=IDLE_SECONDS, help=f"多少秒没新数据算卡住（默认 {IDLE_SECONDS}）")
    p.add_argument("--retries", type=int, default=RETRIES, help=f"最多续传次数（默认 {RETRIES}）")
    a = p.parse_args()
    IDLE_SECONDS, RETRIES = a.idle, a.retries

    if a.address.lower() == "scan":
        asyncio.run(scan())
        return
    try:
        asyncio.run(fetch(a.address, a.last))
    except KeyboardInterrupt:
        print("\n已手动中断，保存已收到的数据 ……")
    finally:
        save_csv(a.output)


if __name__ == "__main__":
    main()
