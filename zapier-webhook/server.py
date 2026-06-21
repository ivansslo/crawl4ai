#!/usr/bin/env python3
"""
Crawl4AI Zapier Webhook Server — lightweight Flask server for Zapier integration.

Endpoints:
  POST /webhook/trigger    — Receive crawl request from Zapier, send result back
  POST /webhook/catch      — Receive crawl result from Crawl4AI for Zapier
  GET  /health             — Health check

Run:
  python server.py              # dev
  gunicorn server:app           # production
"""

import os, json, uuid, logging, threading, requests
from datetime import datetime
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('crawl4ai-zapier')

app = Flask(__name__)

# In-memory store
crawl_store: dict = {}

# ═══════════════════════════════════════════════════════════════════
#  WEBHOOK: Zapier → Crawl4AI (Trigger)
# ═══════════════════════════════════════════════════════════════════
@app.route('/webhook/trigger', methods=['POST'])
def webhook_trigger():
    """
    Zapier sends a URL to crawl. We crawl it and send result back to Zapier.
    
    Zapier input:
      { "url": "https://example.com", "formats": ["markdown"] }
    
    We respond with:
      { "status": "processing", "task_id": "abc123" }
    And POST result to Zapier's webhook URL if provided.
    """
    data = request.get_json(silent=True) or {}
    url = data.get('url', '')
    target_url = data.get('target_url', url)
    formats = data.get('formats', ['markdown'])
    zapier_respond_url = data.get('zapier_respond_url', '')
    
    if not target_url:
        return jsonify({'error': 'Missing target_url or url'}), 400
    
    task_id = str(uuid.uuid4())[:8]
    
    # Run crawl in background thread
    thread = threading.Thread(
        target=_crawl_and_respond,
        args=(task_id, target_url, formats, zapier_respond_url)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'status': 'processing',
        'task_id': task_id,
        'message': f'Crawling {target_url}...'
    })


def _crawl_and_respond(task_id: str, url: str, formats: list, respond_url: str):
    """Crawl URL and optionally send result to Zapier respond URL."""
    try:
        # Try crawl4ai first
        try:
            import asyncio
            from crawl4ai import AsyncWebCrawler
            
            async def do_crawl():
                async with AsyncWebCrawler() as crawler:
                    result = await crawler.arun(url=url, formats=formats)
                    return {
                        'task_id': task_id,
                        'url': url,
                        'status': 'success',
                        'content': result.markdown if 'markdown' in formats else result.html[:100000] if result.html else '',
                        'format': formats[0],
                        'response_time': getattr(result, 'response_time', 0) or 0,
                        'links_count': len(getattr(result, 'links', []) or []),
                    }
            
            result_data = asyncio.run(do_crawl())
        except ImportError:
            # Fallback: requests
            log.info(f"crawl4ai not installed, using requests fallback for {url}")
            start = datetime.now()
            headers = {'User-Agent': 'Mozilla/5.0 (compatible; Crawl4AI/0.9.0)'}
            resp = requests.get(url, headers=headers, timeout=30)
            elapsed = int((datetime.now() - start).total_seconds() * 1000)
            
            import re
            links = re.findall(r'href=["\'](https?://[^"\']+)["\']', resp.text)
            
            result_data = {
                'task_id': task_id,
                'url': url,
                'status': 'success',
                'content': resp.text[:100000] if 'html' in formats or 'text' in formats else resp.text[:50000],
                'format': formats[0],
                'response_time': elapsed,
                'links_count': len(links),
            }
        
        crawl_store[task_id] = result_data
        log.info(f"Crawl complete: {task_id} - {url} ({result_data['response_time']}ms)")
        
        # Send result to Zapier respond URL if provided
        if respond_url:
            payload = {
                'event': 'crawl_complete',
                'task_id': task_id,
                'data': result_data,
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            }
            try:
                r = requests.post(respond_url, json=payload, timeout=30)
                log.info(f"Zapier respond: {respond_url} -> {r.status_code}")
            except Exception as e:
                log.warning(f"Zapier respond failed: {e}")
        
    except Exception as e:
        log.error(f"Crawl failed: {task_id} - {e}")
        error_data = {
            'task_id': task_id,
            'url': url,
            'status': 'error',
            'error': str(e),
        }
        crawl_store[task_id] = error_data
        if respond_url:
            try:
                requests.post(respond_url, json={'event': 'crawl_error', 'data': error_data}, timeout=30)
            except:
                pass


# ═══════════════════════════════════════════════════════════════════
#  WEBHOOK: Crawl4AI → Zapier (Catch)
# ═══════════════════════════════════════════════════════════════════
@app.route('/webhook/catch', methods=['POST'])
def webhook_catch():
    """
    Zapier Catch Hook endpoint.
    Zapier sends a crawl request, we process it and return results inline.
    
    Zapier input:
      { "url": "https://example.com", "formats": ["markdown"] }
    
    Sync response (Zapier expects within 30s):
      { "url": "...", "content": "...", "response_time": 123, "links_count": 5 }
    """
    data = request.get_json(silent=True) or {}
    url = data.get('url', '')
    formats = data.get('formats', ['markdown'])
    
    if not url:
        return jsonify({'error': 'Missing url'}), 400
    
    try:
        try:
            import asyncio
            from crawl4ai import AsyncWebCrawler
            
            async def do_crawl():
                async with AsyncWebCrawler() as crawler:
                    result = await crawler.arun(url=url, formats=formats)
                    return {
                        'url': url,
                        'status': 'success',
                        'content': result.markdown if 'markdown' in formats else result.html[:100000] if result.html else '',
                        'format': formats[0],
                        'response_time': getattr(result, 'response_time', 0) or 0,
                        'links_count': len(getattr(result, 'links', []) or []),
                    }
            
            result_data = asyncio.run(do_crawl())
        except ImportError:
            start = datetime.now()
            headers = {'User-Agent': 'Mozilla/5.0 (compatible; Crawl4AI/0.9.0)'}
            resp = requests.get(url, headers=headers, timeout=30)
            elapsed = int((datetime.now() - start).total_seconds() * 1000)
            
            import re
            links = re.findall(r'href=["\'](https?://[^"\']+)["\']', resp.text)
            
            result_data = {
                'url': url,
                'status': 'success',
                'content': resp.text[:100000] if 'html' in formats or 'text' in formats else resp.text[:50000],
                'format': formats[0],
                'response_time': elapsed,
                'links_count': len(links),
            }
        
        return jsonify(result_data)
        
    except Exception as e:
        log.error(f"Sync crawl failed: {e}")
        return jsonify({'url': url, 'status': 'error', 'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════
#  RESULT: Poll crawl results
# ═══════════════════════════════════════════════════════════════════
@app.route('/result/<task_id>', methods=['GET'])
def get_result(task_id):
    """Poll for crawl result by task_id."""
    result = crawl_store.get(task_id)
    if not result:
        return jsonify({'status': 'not_found', 'task_id': task_id}), 404
    return jsonify(result)


# ═══════════════════════════════════════════════════════════════════
#  HEALTH
# ═══════════════════════════════════════════════════════════════════
@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'service': 'crawl4ai-zapier-webhook',
        'version': '0.9.0',
        'endpoints': {
            'webhook_trigger': 'POST /webhook/trigger (async)',
            'webhook_catch': 'POST /webhook/catch (sync)',
            'get_result': 'GET /result/<task_id>',
        }
    })

@app.route('/', methods=['GET'])
def root():
    return jsonify({
        'name': 'Crawl4AI Zapier Webhook Server',
        'version': '0.9.0',
        'endpoints': {
            'health': 'GET /health',
            'webhook_trigger': 'POST /webhook/trigger',
            'webhook_catch': 'POST /webhook/catch',
            'get_result': 'GET /result/<task_id>',
        },
        'docs': 'See README for Zapier setup guide.'
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')
    debug = os.environ.get('DEBUG', '').lower() in ('1', 'true', 'yes')
    
    log.info(f"🚀 Crawl4AI Zapier Webhook Server")
    log.info(f"   http://{host}:{port}")
    log.info(f"   POST /webhook/trigger  — async crawl + respond to Zapier")
    log.info(f"   POST /webhook/catch    — sync crawl (for Zapier Catch Hook)")
    log.info(f"   GET  /result/<id>       — poll crawl result")
    
    app.run(host=host, port=port, debug=debug)
