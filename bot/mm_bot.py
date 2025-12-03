#!/usr/bin/env python3
import os
import asyncio
import aiohttp
import json
import time
import math
from collections import deque
from decimal import Decimal, ROUND_DOWN
from dotenv import load_dotenv
import signal

load_dotenv()

API_KEY = os.getenv("API_KEY")
API_BASE = os.getenv("API_BASE", "http://localhost:9000")
WS_URL = os.getenv("WS_URL", "ws://localhost:9000/ws")
SYMBOL = os.getenv("SYMBOL", "GHDUSDT")
TARGET_VOLUME_SHARE = float(os.getenv("TARGET_VOLUME_SHARE", "0.05"))
VOLUME_WINDOW = int(os.getenv("VOLUME_WINDOW", "300"))
SPREAD_PCT = float(os.getenv("SPREAD_PCT", "0.002"))
MAX_ORDER_NOTIONAL = float(os.getenv("MAX_ORDER_NOTIONAL", "1000"))
MIN_ORDER_NOTIONAL = float(os.getenv("MIN_ORDER_NOTIONAL", "5"))
TICK_SIZE = float(os.getenv("TICK_SIZE", "0.0001"))
QTY_STEP = float(os.getenv("QTY_STEP", "0.001"))
MAX_POSITION = float(os.getenv("MAX_POSITION", "1000"))
ORDER_REFRESH_SECONDS = 2

def round_price(p):
    return float((Decimal(str(p)) / Decimal(str(TICK_SIZE))).quantize(0, ROUND_DOWN) * Decimal(str(TICK_SIZE)))

def round_qty(q):
    return float((Decimal(str(q)) / Decimal(str(QTY_STEP))).quantize(0, ROUND_DOWN) * Decimal(str(QTY_STEP)))

class RollingVolume:
    def __init__(self, window_seconds):
        self.window = window_seconds
        self.trades = deque()
        self.base_volume = 0.0

    def add_trade(self, ts, qty, price):
        self.trades.append((ts, qty, price))
        self.base_volume += qty
        self._evict_old(ts)

    def _evict_old(self, now):
        cutoff = now - self.window
        while self.trades and self.trades[0][0] < cutoff:
            _, qty, _ = self.trades.popleft()
            self.base_volume -= qty

    def total_volume(self):
        return self.base_volume

class MMBot:
    def __init__(self, session):
        self.session = session
        self.volume = RollingVolume(VOLUME_WINDOW)
        self.order_ids = {}
        self.position = 0.0
        self.last_mid = None
        self.http_sem = asyncio.Semaphore(10)
        self.running = True

    async def rest_post(self, path, payload):
        url = API_BASE.rstrip("/") + path
        headers = {"X-API-KEY": API_KEY, "Content-Type": "application/json"}
        async with self.http_sem:
            async with self.session.post(url, json=payload, headers=headers, timeout=10) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise Exception(f"POST {url} -> {resp.status}: {text}")
                return await resp.json()

    async def rest_delete(self, path):
        url = API_BASE.rstrip("/") + path
        headers = {"X-API-KEY": API_KEY}
        async with self.http_sem:
            async with self.session.delete(url, headers=headers, timeout=10) as resp:
                return await resp.json()

    async def on_trade(self, trade):
        ts = trade["ts"]
        qty = float(trade["quantity"])
        price = float(trade["price"])
        self.volume.add_trade(ts, qty, price)

    async def on_orderbook(self, ob):
        best_bid = float(ob["bestBid"])
        best_ask = float(ob["bestAsk"])
        self.last_mid = (best_bid + best_ask) / 2.0

    async def place_limit(self, side, price, qty):
        price = round_price(price)
        qty = round_qty(qty)
        if qty <= 0:
            return None
        payload = {
            "symbol": SYMBOL,
            "side": "BUY" if side == "buy" else "SELL",
            "price": price,
            "quantity": qty,
            "timeInForce": "GTC"
        }
        try:
            res = await self.rest_post("/orders", payload)
            return res
        except Exception as e:
            print("place_limit error:", e)
            return None

    async def cancel_order(self, order_id):
        try:
            res = await self.rest_delete(f"/orders/{order_id}")
            return res
        except Exception as e:
            print("cancel order error:", e)
            return None

    async def compute_and_place(self):
        if self.last_mid is None:
            return

        market_vol = self.volume.total_volume()
        if market_vol <= 0:
            max_order_base = MIN_ORDER_NOTIONAL / self.last_mid
        else:
            desired_base_per_window = TARGET_VOLUME_SHARE * market_vol
            expected_fill_rate = 0.2
            expected_needed_base = desired_base_per_window * expected_fill_rate
            max_order_base = expected_needed_base / 2.0

        order_notional = min(MAX_ORDER_NOTIONAL, max(MIN_ORDER_NOTIONAL, max_order_base * self.last_mid))
        order_qty = round_qty(order_notional / self.last_mid)
        if order_qty * self.last_mid < MIN_ORDER_NOTIONAL:
            order_qty = round_qty(MIN_ORDER_NOTIONAL / self.last_mid)

        spread = SPREAD_PCT
        buy_price = round_price(self.last_mid * (1 - spread/2))
        sell_price = round_price(self.last_mid * (1 + spread/2))

        if self.position + order_qty > MAX_POSITION:
            buy_qty = max(0.0, round_qty(MAX_POSITION - self.position))
        else:
            buy_qty = order_qty
        if self.position - order_qty < -MAX_POSITION:
            sell_qty = max(0.0, round_qty(self.position + MAX_POSITION))
        else:
            sell_qty = order_qty

        remote_ids = list(self.order_ids.values())
        for oid in remote_ids:
            await self.cancel_order(oid)
        self.order_ids.clear()

        if buy_qty * self.last_mid >= MIN_ORDER_NOTIONAL:
            r = await self.place_limit("buy", buy_price, buy_qty)
            if r and "id" in r:
                self.order_ids[f"buy_{int(time.time())}"] = r["id"]

        if sell_qty * self.last_mid >= MIN_ORDER_NOTIONAL:
            r = await self.place_limit("sell", sell_price, sell_qty)
            if r and "id" in r:
                self.order_ids[f"sell_{int(time.time())}"] = r["id"]

    async def ws_consume(self):
        import websockets
        async with websockets.connect(WS_URL, extra_headers=[("X-API-KEY", API_KEY)]) as ws:
            subscribe = {"type": "subscribe", "symbol": SYMBOL, "channels": ["trades", "orderbook"]}
            await ws.send(json.dumps(subscribe))
            while self.running:
                msg = await ws.recv()
                data = json.loads(msg)
                if data.get("type") == "trade":
                    await self.on_trade(data)
                elif data.get("type") == "orderbook":
                    await self.on_orderbook(data)

    async def bot_loop(self):
        while self.running:
            try:
                await self.compute_and_place()
            except Exception as e:
                print("error in compute_and_place:", e)
            await asyncio.sleep(ORDER_REFRESH_SECONDS)

async def main():
    async with aiohttp.ClientSession() as sess:
        bot = MMBot(sess)
        ws_task = asyncio.create_task(bot.ws_consume())
        bot_task = asyncio.create_task(bot.bot_loop())
        def _stop(sig, frame):
            bot.running = False
        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
        try:
            await asyncio.gather(ws_task, bot_task)
        except asyncio.CancelledError:
            bot.running = False

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("shutdown")
