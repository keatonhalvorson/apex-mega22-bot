import time
import random
import urllib.request
import urllib.error
import socket
from playwright.sync_api import sync_playwright

# List of realistic user agents to vary the fingerprint
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15"
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1280, "height": 720}
]

def get_working_proxies():
    """
    Fetches free HTTP proxies from multiple public GitHub lists
    and yields working ones as they are found.
    """
    print("[*] Fetching free proxies list from GitHub sources...")
    urls = [
        "https://raw.githubusercontent.com/komutan234/Proxy-List-Free/main/proxies/http.txt",
        "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt",
        "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt"
    ]
    
    proxies = []
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as response:
                content = response.read().decode('utf-8').splitlines()
                proxies.extend(content)
        except Exception as e:
            print(f"[-] Error fetching from {url}: {e}")
            
    # Clean and remove duplicates
    proxies = list(set([p.strip() for p in proxies if p.strip()]))
    print(f"[+] Loaded {len(proxies)} unique proxies. Selecting and testing...")
    
    random.shuffle(proxies)
    socket.setdefaulttimeout(3.0) # Set socket timeout for fast checking
    
    # Test proxies and yield working ones
    tested_count = 0
    max_tests = 100
    for proxy in proxies:
        if tested_count >= max_tests:
            break
        tested_count += 1
        print(f"[*] [{tested_count}] Testing proxy: {proxy} ... ", end="", flush=True)
        try:
            proxy_handler = urllib.request.ProxyHandler({'http': proxy, 'https': proxy})
            opener = urllib.request.build_opener(proxy_handler)
            opener.addheaders = [('User-Agent', random.choice(USER_AGENTS))]
            
            # Step 1: verify basic connectivity
            with opener.open("https://httpbin.org/ip", timeout=3.0) as resp:
                # Step 2: verify connection to ChatGPT's domain (not blocked/reset)
                try:
                    # Requesting chatgpt.com will likely return 403 Forbidden, which is fine
                    # (it means connection succeeded, SSL shook hands, and we got a Cloudflare response).
                    # If it raises HTTPError with 403/401/404/etc, we count it as a network success.
                    # If it raises URLError (timeout, connection reset, proxy error), it's a failure.
                    with opener.open("https://chatgpt.com", timeout=3.0) as chat_resp:
                        pass
                except urllib.error.HTTPError as e:
                    if e.code not in [403, 401, 301, 302, 404]:
                        raise Exception(f"HTTPError {e.code}")
                
                print("Working!")
                yield proxy
        except Exception as e:
            print(f"Failed ({type(e).__name__})")

def run_with_proxy(proxy_ip):
    if not proxy_ip:
        proxy_config = None
    else:
        proxy_config = {"server": f"http://{proxy_ip}"}

    user_agent = random.choice(USER_AGENTS)
    viewport = random.choice(VIEWPORTS)
    
    print(f"[*] Chosen User-Agent: {user_agent}")
    print(f"[*] Chosen Viewport: {viewport['width']}x{viewport['height']}")

    with sync_playwright() as p:
        launch_args = {
            "headless": False,
            "args": [
                "--disable-blink-features=AutomationControlled", # Prevents webdriver detection
                "--no-sandbox"
            ]
        }
        if proxy_config:
            launch_args["proxy"] = proxy_config
            
        try:
            browser = p.chromium.launch(**launch_args)
        except Exception as e:
            print(f"[-] Failed to launch browser: {e}")
            return False
            
        try:
            context = browser.new_context(
                user_agent=user_agent,
                viewport=viewport,
                locale="en-US",
                timezone_id="America/New_York"
            )
            context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            page = context.new_page()
            
            print("[+] Navigating to ChatGPT...")
            # Using 40s timeout for quicker retries if a proxy hangs
            page.goto("https://chatgpt.com/", timeout=40000, wait_until="domcontentloaded")
            print("[+] Successfully entered ChatGPT!")
            print(f"[+] Current Page Title: {page.title()}")
            
            print("[*] Browser is open. It will stay open until you close the browser window...")
            try:
                page.wait_for_event("close", timeout=0)
            except Exception:
                pass
            return True
            
        except Exception as e:
            err_msg = str(e)
            print(f"[-] Error navigating to ChatGPT: {e}")
            if "Target closed" in err_msg or "Browser closed" in err_msg:
                # User closed the browser, so don't try other proxies
                return True
            return False
        finally:
            browser.close()
            print("[+] Session closed and all temporary data (cookies/cache) completely wiped!")

def visit_chatgpt():
    proxy_generator = get_working_proxies()
    
    max_attempts = 5
    attempt = 0
    
    while attempt < max_attempts:
        try:
            proxy_ip = next(proxy_generator)
        except StopIteration:
            print("[-] No more working proxies found in the list.")
            proxy_ip = None
            
        if not proxy_ip:
            if attempt == 0:
                print("[!] Warning: Could not find any working free proxy. Running WITHOUT proxy...")
            else:
                print("[!] Warning: No more working proxies. Running WITHOUT proxy...")
            run_with_proxy(None)
            break
            
        attempt += 1
        print(f"\n[+] Attempt {attempt}/{max_attempts}: Running browser through proxy: {proxy_ip}")
        success = run_with_proxy(proxy_ip)
        if success:
            break

if __name__ == "__main__":
    visit_chatgpt()
