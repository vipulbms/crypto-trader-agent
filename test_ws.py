import asyncio, websockets, json
async def main():
    async with websockets.connect('wss://ws.kraken.com/v2') as ws:
        await ws.send(json.dumps({'method':'subscribe', 'params': {'channel': 'ticker', 'symbol': ['BTC/USD']}}))
        for _ in range(3): print(await ws.recv())
asyncio.run(main())
