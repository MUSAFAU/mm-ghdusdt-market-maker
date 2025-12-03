# Simple mock exchange with HMAC verification and websockets for market data
import asyncio
import hmac, hashlib, json, time
from aiohttp import web, WSMsgType

API_KEYS = {
    "testkey": "testsecret"
}

def verify_signature(api_key, timestamp, signature, method, path, body):
    secret = API_KEYS.get(api_key)
    if not secret:
        return False
    message = f"{timestamp}{method}{path}{body}"
    expected = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

async def handle_balance(request):
    api_key = request.headers.get("X-API-KEY")
    ts = request.headers.get("X-TIMESTAMP", "")
    sig = request.headers.get("X-SIGNATURE", "")
    body = ""
    if not verify_signature(api_key, ts, sig, "GET", "/account/balance", body):
        return web.json_response({"error":"invalid signature"}, status=401)
    return web.json_response({"balances":[{"asset":"GHD","free":1000,"locked":0},{"asset":"USDT","free":10000,"locked":0}]})

ORDERS = {}
ORDER_ID_SEQ = 1

async def handle_orders(request):
    global ORDER_ID_SEQ
    api_key = request.headers.get("X-API-KEY")
    ts = request.headers.get("X-TIMESTAMP", "")
    sig = request.headers.get("X-SIGNATURE", "")
    body = await request.text()
    if not verify_signature(api_key, ts, sig, "POST", "/orders", body):
        return web.json_response({"error":"invalid signature"}, status=401)
    data = await request.json()
    oid = str(ORDER_ID_SEQ); ORDER_ID_SEQ += 1
    ORDERS[oid] = dict(id=oid, **data, executedQuantity=0, status="NEW")
    return web.json_response(ORDERS[oid], status=201)

async def handle_cancel(request):
    api_key = request.headers.get("X-API-KEY")
    ts = request.headers.get("X-TIMESTAMP", "")
    sig = request.headers.get("X-SIGNATURE", "")
    oid = request.match_info['orderId']
    body = ""
    if not verify_signature(api_key, ts, sig, "DELETE", f"/orders/{oid}", body):
        return web.json_response({"error":"invalid signature"}, status=401)
    if oid in ORDERS:
        ORDERS[oid]['status'] = 'CANCELLED'
        return web.json_response(ORDERS[oid])
    return web.json_response({"error":"not found"}, status=404)

routes = web.RouteTableDef()

@routes.get('/account/balance')
async def account_balance(req):
    return await handle_balance(req)

@routes.post('/orders')
async def orders(req):
    return await handle_orders(req)

@routes.delete('/orders/{orderId}')
async def cancel(req):
    return await handle_cancel(req)

async def ws_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    # simple loop: send synthetic orderbook and trades every second
    try:
        while True:
            ob = {"type":"orderbook","bestBid":0.0995,"bestAsk":0.1005}
            await ws.send_str(json.dumps(ob))
            trade = {"type":"trade","ts":int(time.time()),"price":0.1000,"quantity":10}
            await ws.send_str(json.dumps(trade))
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    return ws

app = web.Application()
app.add_routes(routes)
app.router.add_get('/ws', ws_handler)

if __name__ == '__main__':
    web.run_app(app, port=9000)
