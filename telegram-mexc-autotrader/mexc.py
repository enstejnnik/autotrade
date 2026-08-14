"""
MEXC Futures API client using aiohttp.
Implements async requests with retries, timeouts, and signature authentication.
API documentation: https://mexcdevelop.github.io/apidocs/contract/
"""

import asyncio
import hashlib
import hmac
import time
from typing import Optional, Dict, Any
from aiohttp import ClientSession, ClientTimeout
from loguru import logger

from config import MEXC_BASE_URL, MEXC_API_KEY, MEXC_SECRET


class MexcClient:
    """Async MEXC Futures API client."""
    
    def __init__(self, dry_run: bool = False):
        self.api_key = MEXC_API_KEY
        self.secret = MEXC_SECRET
        self.base_url = MEXC_BASE_URL
        self.dry_run = dry_run
        self._session: Optional[ClientSession] = None
        self._timeout = ClientTimeout(total=30)
    
    async def _get_session(self) -> ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = ClientSession(timeout=self._timeout)
        return self._session
    
    async def close(self):
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    def _generate_signature(self, timestamp: int) -> str:
        """Generate HMAC-SHA256 signature."""
        # Signature = hex(HMAC_SHA256(accessKey + timestamp, secretKey))
        message = f"{self.api_key}{timestamp}"
        signature = hmac.new(
            self.secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def _get_headers(self, timestamp: int) -> Dict[str, str]:
        """Get request headers with signature."""
        return {
            "ApiKey": self.api_key,
            "Request-Time": str(timestamp),
            "Signature": self._generate_signature(timestamp)
        }
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Make API request with retry logic."""
        url = f"{self.base_url}{endpoint}"
        
        for attempt in range(3):
            try:
                timestamp = int(time.time() * 1000)
                headers = self._get_headers(timestamp)
                
                session = await self._get_session()
                
                if method == "GET":
                    async with session.get(url, params=params, headers=headers) as resp:
                        result = await resp.json()
                elif method == "POST":
                    async with session.post(url, json=data, headers=headers) as resp:
                        result = await resp.json()
                else:
                    raise ValueError(f"Unsupported method: {method}")
                
                logger.debug(f"MEXC {method} {endpoint}: {result}")
                
                # Check for error codes
                if isinstance(result, dict):
                    if result.get("code") == 200 or result.get("success"):
                        return result
                    # Some endpoints return code 0 for success
                    if result.get("code") == 0:
                        return result
                
                logger.warning(f"MEXC API error: {result}")
                return None
                
            except Exception as e:
                wait_time = (2 ** attempt) * 0.5  # Exponential backoff
                logger.warning(f"MEXC request failed (attempt {attempt+1}): {e}, retrying in {wait_time}s")
                await asyncio.sleep(wait_time)
        
        logger.error(f"MEXC request failed after 3 attempts: {endpoint}")
        return None
    
    async def get_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get ticker info for a symbol."""
        # GET /api/v1/contract/ticker/{symbol}
        endpoint = f"/api/v1/contract/ticker/{symbol}"
        return await self._request("GET", endpoint)
    
    async def get_detail(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get contract detail including precision info."""
        # GET /api/v1/contract/detail/{symbol}
        endpoint = f"/api/v1/contract/detail/{symbol}"
        return await self._request("GET", endpoint)
    
    async def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get open position for a symbol."""
        # GET /api/v1/contract/open_positions/{symbol}
        endpoint = f"/api/v1/contract/open_positions/{symbol}"
        return await self._request("GET", endpoint)
    
    async def change_leverage(self, symbol: str, leverage: int) -> bool:
        """Change leverage for a symbol."""
        # POST /api/v1/contract/change_leverage
        endpoint = "/api/v1/contract/change_leverage"
        data = {
            "symbol": symbol,
            "leverage": leverage
        }
        result = await self._request("POST", endpoint, data=data)
        return result is not None
    
    async def submit_order(
        self,
        symbol: str,
        side: int,
        order_type: int,
        price: float = 0.0,
        vol: int = 0,
        reduce_only: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Submit an order.
        
        Side codes (per MEXC docs):
        1 = Open Long
        2 = Close Short
        3 = Open Short
        4 = Close Long
        
        Type codes:
        1 = Limit
        2 = Market
        
        openType: 1 = Isolated, 2 = Cross
        """
        if self.dry_run:
            logger.info(f"[DRY-RUN] Order: {symbol} side={side} type={order_type} price={price} vol={vol}")
            return {"orderId": f"dry_{int(time.time()*1000)}", "symbol": symbol}
        
        endpoint = "/api/v1/contract/order/submit"
        data = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "vol": vol,
            "openType": 1  # Isolated margin
        }
        
        if order_type == 1:  # Limit
            data["price"] = price
        
        if reduce_only:
            data["reduceOnly"] = True
        
        result = await self._request("POST", endpoint, data=data)
        return result
    
    async def submit_trigger_order(
        self,
        symbol: str,
        side: int,
        trigger_price: float,
        vol: int,
        reduce_only: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Submit a trigger stop-market order.
        Per MEXC docs for trigger orders.
        """
        if self.dry_run:
            logger.info(f"[DRY-RUN] Trigger order: {symbol} side={side} trigger={trigger_price} vol={vol}")
            return {"orderId": f"dry_stop_{int(time.time()*1000)}", "symbol": symbol}
        
        endpoint = "/api/v1/contract/order/trigger"
        data = {
            "symbol": symbol,
            "side": side,
            "vol": vol,
            "triggerType": "LAST_PRICE",  # Or MARK_PRICE
            "triggerPrice": trigger_price,
            "orderType": "MARKET",
            "openType": 1
        }
        
        if reduce_only:
            data["reduceOnly"] = True
        
        result = await self._request("POST", endpoint, data=data)
        return result
    
    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an order."""
        if self.dry_run:
            logger.info(f"[DRY-RUN] Cancel order: {symbol} id={order_id}")
            return True
        
        endpoint = f"/api/v1/contract/order/cancel/{symbol}/{order_id}"
        result = await self._request("DELETE", endpoint)
        return result is not None
    
    async def get_open_orders(self, symbol: str) -> list:
        """Get open orders for a symbol."""
        endpoint = f"/api/v1/contract/open_orders/{symbol}"
        result = await self._request("GET", endpoint)
        if result and "data" in result:
            return result["data"] if isinstance(result["data"], list) else [result["data"]]
        return []
    
    async def cancel_all_orders(self, symbol: str) -> bool:
        """Cancel all open orders for a symbol."""
        if self.dry_run:
            logger.info(f"[DRY-RUN] Cancel all orders: {symbol}")
            return True
        
        endpoint = f"/api/v1/contract/order/cancel/{symbol}"
        result = await self._request("DELETE", endpoint)
        return result is not None
