# API Research: Binance USDⓈ-M Futures

This document summarizes key findings for interacting with the Binance USDⓈ-M Futures API.

## 1. Base URLs

### REST API
*   **Production:** `https://fapi.binance.com`
*   **Testnet:** `https://testnet.binancefuture.com`

### WebSocket API
*   **Production:** `wss://fstream.binance.com`
*   **Testnet:** `wss://fstream.binancefuture.com`

## 2. Key REST Endpoints (Market Data)

All endpoints are prefixed with the REST Base URL. Example: `https://fapi.binance.com/fapi/v1/klines`

*   **Klines/Candlestick Data (`GET /fapi/v1/klines`)**
    *   **Purpose:** Get kline/candlestick bars for a symbol. Klines are uniquelyidentified by their open time.
    *   **Key Parameters:**
        *   `symbol` (STRING, MANDATORY): Trading symbol (e.g., BTCUSDT).
        *   `interval` (ENUM, MANDATORY): Kline interval (e.g., 1m, 5m, 1h, 1d).
        *   `startTime` (LONG, OPTIONAL): Start time in milliseconds.
        *   `endTime` (LONG, OPTIONAL): End time in milliseconds.
        *   `limit` (INT, OPTIONAL): Default 500; max 1500.
    *   **Security:** NONE (No API Key needed)

*   **Order Book (`GET /fapi/v1/depth`)**
    *   **Purpose:** Get the order book (bids and asks).
    *   **Key Parameters:**
        *   `symbol` (STRING, MANDATORY): Trading symbol.
        *   `limit` (INT, OPTIONAL): Default 500. Valid limits: [5, 10, 20, 50, 100, 500, 1000].
    *   **Security:** NONE

*   **Recent Trades List (`GET /fapi/v1/trades`)**
    *   **Purpose:** Get recent trades.
    *   **Key Parameters:**
        *   `symbol` (STRING, MANDATORY): Trading symbol.
        *   `limit` (INT, OPTIONAL): Default 500; max 1000.
    *   **Security:** NONE

*   **Mark Price and Premium Index (`GET /fapi/v1/premiumIndex`)**
    *   **Purpose:** Get Mark Price and Premium Index for a single symbol or all symbols.
    *   **Key Parameters:**
        *   `symbol` (STRING, OPTIONAL): Trading symbol. If omitted, data for all symbols is returned.
    *   **Security:** NONE

*   **Funding Rate History (`GET /fapi/v1/fundingRate`)**
    *   **Purpose:** Get funding rate history.
    *   **Key Parameters:**
        *   `symbol` (STRING, OPTIONAL): Trading symbol.
        *   `startTime` (LONG, OPTIONAL): Start time in milliseconds.
        *   `endTime` (LONG, OPTIONAL): End time in milliseconds.
        *   `limit` (INT, OPTIONAL): Default 100; max 1000.
    *   **Security:** NONE

*   **Get Funding Info (`GET /fapi/v1/fundingInfo`)**
    *   **Purpose:** Get current funding rate information. (This might be more suitable for the latest rate than `/fapi/v1/fundingRate` which is historical).
    *   **Key Parameters:**
        *   `symbol` (STRING, OPTIONAL): Trading symbol.
    *   **Security:** NONE

## 3. Key WebSocket Streams (Market Data)

Connection URL format:
*   Single stream: `wss://fstream.binance.com/ws/<streamName>`
*   Combined streams: `wss://fstream.binance.com/stream?streams=<streamName1>/<streamName2>/...`

*   **Aggregate Trade Streams**
    *   **Stream Name:** `<symbol>@aggTrade` (e.g., `btcusdt@aggTrade`)
    *   **Payload:** Information about an aggregated trade (price, quantity, timestamp, buyer maker status).
    *   **Update Speed:** Real-time.

*   **Mark Price Stream (Per Symbol)**
    *   **Stream Name:** `<symbol>@markPrice@1s` (updates every 1 second) or `<symbol>@markPrice` (updates every 3 seconds)
    *   **Payload:** Mark price, index price, estimated settle price, funding rate, next funding time.
    *   **Update Speed:** 1 second or 3 seconds.

*   **Kline/Candlestick Streams**
    *   **Stream Name:** `<symbol>@kline_<interval>` (e.g., `btcusdt@kline_1m`)
    *   **Payload:** Kline data (open time, open, high, low, close, volume, close time, etc.) for the specified interval.
    *   **Update Speed:** Updates when a kline for the interval closes.

*   **Partial Book Depth Streams**
    *   **Stream Name:** `<symbol>@depth<levels>@<updateSpeed>` (e.g., `btcusdt@depth5@100ms`)
    *   **Levels:** 5, 10, 20.
    *   **Update Speed:** 100ms, 500ms, or 0ms (real-time, use with caution for diff depth).
    *   **Payload:** Snapshot of the top <levels> bids and asks.

*   **Diff. Book Depth Streams**
    *   **Stream Name:** `<symbol>@depth@<updateSpeed>` (e.g., `btcusdt@depth@100ms`)
    *   **Update Speed:** 100ms, 500ms, or 0ms (real-time).
    *   **Payload:** Incremental updates to the order book (bids and asks to be updated, added, or removed). Requires local order book management.

## 4. Authentication

*   **API Key:** Passed in the `X-MBX-APIKEY` HTTP header.
*   **Signature (for `SIGNED` endpoints - TRADE, USER_DATA):**
    *   Uses HMAC SHA256.
    *   `secretKey` is used as the key for the HMAC operation.
    *   The data to be signed is the `totalParams` (query string concatenated with request body for POST/PUT/DELETE).
    *   The signature is sent as the `signature` parameter in the query string or request body.
*   **Timestamp:** `SIGNED` endpoints require a `timestamp` parameter (milliseconds of request creation).
*   **RecvWindow:** Optional `recvWindow` parameter (default 5000ms) specifies the validity window for the request. Recommended to use a small value (e.g., 5000ms or less).
*   RSA key signing is also supported as an alternative to HMAC SHA256.

## 5. Rate Limits

*   **General:**
    *   Checked per IP address.
    *   Response headers `X-MBX-USED-WEIGHT-(intervalNum)(intervalLetter)` indicate current used weight.
    *   HTTP `429` returned when a rate limit is violated.
    *   HTTP `418` returned if an IP is auto-banned for repeatedly violating limits after receiving 429s. Bans scale from 2 minutes to 3 days.
*   **Order Rate Limits:**
    *   Checked per account.
    *   Response header `X-MBX-ORDER-COUNT-(intervalNum)(intervalLetter)` indicates current order count.
*   It is strongly recommended to use WebSocket streams for market data to reduce request load.

## 6. WebSocket PING/PONG

*   The server sends a PING frame every 3 minutes.
*   If the server does not receive a PONG frame back from the connection within a 10-minute period, the connection will be disconnected.
*   Clients can send unsolicited PONG frames to maintain the connection.

## 7. Official Python SDK

*   **Name:** `binance-futures-connector-python`
*   **Repository:** `https://github.com/binance/binance-futures-connector-python`
*   **Installation:** `pip install binance-futures-connector`

This research provides a foundational understanding for developing with the Binance USDⓈ-M Futures API. Refer to the official Binance API documentation for complete details and updates.
